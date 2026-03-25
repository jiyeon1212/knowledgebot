import asyncio
import logging
import re
import traceback
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.atlassian_user import AtlassianUser
from app.models.oauth_state import OAuthState
from app.auth.google_oauth import build_auth_url
from app.auth.atlassian_oauth import build_atlassian_auth_url
from app.google.gmail import search_gmail
from app.google.drive import search_drive, search_drive_by_project
from app.google.token_refresh import get_valid_access_token
from app.atlassian.token_refresh import get_valid_atlassian_token, AtlassianReauthRequired
from app.atlassian.confluence import search_confluence, search_confluence_by_project
from app.atlassian.jira import search_jira, search_jira_by_project
from app.ai.summarizer import (
    classify_intent, generate_chat_response, summarize_results,
    filter_irrelevant_results, filter_by_category,
)
from app.search.query_builder import (
    build_gmail_query, CATEGORY_KEYWORDS,
    is_project_search, parse_search_command,
)
from app.slack.block_kit import format_search_response

logger = logging.getLogger(__name__)

_STATE_TTL_MINUTES = 10


def _distribute_results(
    processed: list[list],
    google_connected: bool,
    atlassian_connected: bool,
) -> tuple[list, list, list, list]:
    """gather 결과를 서비스별로 분배한다.

    processed 리스트의 순서는 tasks 빌드 순서와 동일:
      Google 연결 시: [gmail, drive, ...]
      Atlassian 연결 시: [..., confluence, jira]
    """
    idx = 0
    gmail_results: list = []
    drive_results: list = []
    confluence_results: list = []
    jira_results: list = []

    if google_connected:
        gmail_results = processed[idx]
        idx += 1
        drive_results = processed[idx]
        idx += 1

    if atlassian_connected:
        confluence_results = processed[idx]
        idx += 1
        jira_results = processed[idx]
        idx += 1

    return gmail_results, drive_results, confluence_results, jira_results


async def handle_dm(user_id: str, text: str, say) -> None:
    try:
        # 0-1. #검색 포맷 감지 → 프로젝트 기반 검색
        if is_project_search(text):
            parsed = parse_search_command(text)
            if parsed is None:
                await say(
                    "입력 형식을 확인해주세요.\n"
                    "예: `#검색 상호운용 /개발`\n"
                    "예: `#검색 미래에셋, 신한 /사업 /최근 3개월`"
                )
                return

            # 기간 자연어 → AI 파싱
            date_from = None
            date_to = None
            if parsed["period_text"]:
                period_result = await classify_intent(parsed["period_text"])
                date_from = period_result.get("date_from")
                date_to = period_result.get("date_to")

            project_label = ", ".join(parsed["project_names"])
            category_label = "사업" if parsed["category"] == "business" else "개발"
            await say(f"🔍 *{project_label}* ({category_label}) 검색을 시작합니다...")

            await handle_project_search(
                user_id=user_id,
                project_names=parsed["project_names"],
                category=parsed["category"],
                date_from=date_from,
                date_to=date_to,
                say=say,
            )
            return

        # 0-2. [키워드] 직접 지정 감지 — AI 의도 분류 건너뜀
        bracket_matches = re.findall(r"\[([^\]]+)\]", text)
        if bracket_matches:
            keyword = " ".join(bracket_matches)
            max_results = 100
            intent = "search"
            date_from = None
            date_to = None
            logger.info("사용자 지정 키워드: %s (원문: %s)", keyword, text)
        else:
            # 1. 의도 분류
            intent_result = await classify_intent(text)
            intent = intent_result["intent"]

            # 2. chat 의도 → AI 직접 답변
            if intent == "chat":
                response = await generate_chat_response(text, user_id=user_id)
                await say(response)
                return

            # 3. search 의도 → 검색 흐름
            keyword = intent_result.get("search_keyword") or text
            max_results = intent_result.get("max_results") or 100
            date_from = intent_result.get("date_from")
            date_to = intent_result.get("date_to")

        if date_from or date_to:
            logger.info("날짜 필터: %s ~ %s", date_from, date_to)

        async with AsyncSessionLocal() as db:
            # 사용자 계정 조회 (Google + Atlassian)
            google_result = await db.execute(
                select(User).where(User.slack_user_id == user_id)
            )
            google_user = google_result.scalar_one_or_none()

            atlassian_result = await db.execute(
                select(AtlassianUser).where(AtlassianUser.slack_user_id == user_id)
            )
            atlassian_user = atlassian_result.scalar_one_or_none()

            # 두 계정 모두 미연결 → 로그인 버튼 모두 표시
            if not google_user and not atlassian_user:
                google_auth_url, google_state = build_auth_url()
                atlassian_auth_url, atlassian_state = build_atlassian_auth_url()

                # OAuth state 저장
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(minutes=_STATE_TTL_MINUTES)
                db.add(OAuthState(
                    state=google_state,
                    slack_user_id=user_id,
                    expires_at=expires_at,
                ))
                db.add(OAuthState(
                    state=atlassian_state,
                    slack_user_id=user_id,
                    expires_at=expires_at,
                ))
                await db.commit()

                await say(
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "안녕하세요! 검색을 위해 계정을 연결해주세요.",
                            },
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Google 로그인"},
                                    "url": google_auth_url,
                                    "action_id": "google_oauth_login",
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Atlassian 로그인"},
                                    "url": atlassian_auth_url,
                                    "action_id": "atlassian_oauth_login",
                                },
                            ],
                        },
                    ],
                    text="계정 연결이 필요합니다.",
                )
                return

            # 연결된 서비스에 대해 토큰 획득 및 검색 태스크 빌드
            google_connected = False
            atlassian_connected = False
            tasks = []

            if google_user:
                try:
                    access_token = await get_valid_access_token(user=google_user, db=db)
                    google_connected = True
                    tasks.append(search_gmail(access_token=access_token, query=keyword, max_results=max_results, date_from=date_from, date_to=date_to))
                    tasks.append(search_drive(access_token=access_token, query=keyword, max_results=max_results, date_from=date_from, date_to=date_to))
                except Exception:
                    logger.exception("Google 토큰 획득 실패 (user_id=%s)", user_id)

            if atlassian_user:
                try:
                    atl_token, cloud_id = await get_valid_atlassian_token(user=atlassian_user, db=db)
                    atlassian_connected = True
                    tasks.append(search_confluence(atl_token, cloud_id, keyword, max_results=max_results, date_from=date_from, date_to=date_to))
                    tasks.append(search_jira(atl_token, cloud_id, keyword, max_results=max_results, date_from=date_from, date_to=date_to))
                except AtlassianReauthRequired:
                    logger.warning("Atlassian 재인증 필요 (user_id=%s)", user_id)
                except Exception:
                    logger.exception("Atlassian 토큰 획득 실패 (user_id=%s)", user_id)

            # 연결된 서비스가 없는 경우 (토큰 획득 모두 실패)
            if not tasks:
                await say("서비스 연결에 문제가 발생했습니다. 다시 인증해 주세요.")
                return

            # 병렬 검색 실행
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 예외 처리: Exception → 빈 리스트 + 로깅
            processed = []
            for r in results:
                if isinstance(r, Exception):
                    logger.error("서비스 검색 실패: %s", r)
                    processed.append([])
                else:
                    processed.append(r)

            # 결과 분배
            gmail_results, drive_results, confluence_results, jira_results = _distribute_results(
                processed, google_connected, atlassian_connected
            )

        print(f"[DEBUG] 검색 결과: Gmail={len(gmail_results)}건, Drive={len(drive_results)}건, Confluence={len(confluence_results)}건, Jira={len(jira_results)}건 (keyword={keyword})")

        # 필터링 전 문서 제목 로그
        for i, m in enumerate(gmail_results):
            print(f"[DEBUG] [필터전] Gmail[{i}]: {m.get('subject', '')}")
        for i, f in enumerate(drive_results):
            print(f"[DEBUG] [필터전] Drive[{i}]: {f.get('name', '')}")
        for i, c in enumerate(confluence_results):
            print(f"[DEBUG] [필터전] Confluence[{i}]: {c.get('title', '')}")
        for i, j in enumerate(jira_results):
            print(f"[DEBUG] [필터전] Jira[{i}]: [{j.get('key', '')}] {j.get('title', '')}")

        # AI 관련성 필터링 (방법 1: 관련 없는 결과 제거)
        # 필터링은 사용자 원문 텍스트 기준으로 수행 (AI 추출 키워드가 불완전할 수 있으므로)
        gmail_results, drive_results, confluence_results, jira_results = await asyncio.gather(
            filter_irrelevant_results(text, gmail_results, "gmail"),
            filter_irrelevant_results(text, drive_results, "drive"),
            filter_irrelevant_results(text, confluence_results, "confluence"),
            filter_irrelevant_results(text, jira_results, "jira"),
        )

        print(f"[DEBUG] 필터링 후: Gmail={len(gmail_results)}건, Drive={len(drive_results)}건, Confluence={len(confluence_results)}건, Jira={len(jira_results)}건 (keyword={keyword})")

        # 필터링 후 전체 결과가 0건이면 관련 결과 없음 메시지
        total_after_filter = len(gmail_results) + len(drive_results) + len(confluence_results) + len(jira_results)
        if total_after_filter == 0:
            await say(f"🔍 '{keyword}' 관련 검색 결과를 찾지 못했습니다. 다른 키워드로 검색해 보세요.")
            return

        # 요약 생성
        summary = await summarize_results(
            question=text,
            gmail_results=gmail_results,
            drive_results=drive_results,
            confluence_results=confluence_results,
            jira_results=jira_results,
            user_id=user_id,
        )

        # Block Kit 포맷팅 (미연결 서비스 안내 포함)
        connect_google = not google_connected
        connect_atlassian = not atlassian_connected

        google_auth_url = None
        atlassian_auth_url = None
        if connect_google or connect_atlassian:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(minutes=_STATE_TTL_MINUTES)
                if connect_google:
                    google_auth_url, google_state = build_auth_url()
                    db.add(OAuthState(
                        state=google_state,
                        slack_user_id=user_id,
                        expires_at=expires_at,
                    ))
                if connect_atlassian:
                    atlassian_auth_url, atlassian_state = build_atlassian_auth_url()
                    db.add(OAuthState(
                        state=atlassian_state,
                        slack_user_id=user_id,
                        expires_at=expires_at,
                    ))
                    logger.info("Atlassian OAuth state 저장: state=%s, user=%s", atlassian_state[:16], user_id)
                await db.commit()
                logger.info("OAuth state DB commit 완료")

        blocks = format_search_response(
            summary_text=summary,
            gmail_results=gmail_results,
            drive_results=drive_results,
            confluence_results=confluence_results,
            jira_results=jira_results,
            connect_google=connect_google,
            connect_atlassian=connect_atlassian,
            google_auth_url=google_auth_url,
            atlassian_auth_url=atlassian_auth_url,
        )

        # 날짜 필터 배너 추가
        if date_from or date_to:
            date_banner = "📅 "
            if date_from and date_to:
                date_banner += f"{date_from} ~ {date_to} 기간으로 검색했습니다"
            elif date_from:
                date_banner += f"{date_from} 이후로 검색했습니다"
            else:
                date_banner += f"{date_to} 이전으로 검색했습니다"
            blocks.insert(0, {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": date_banner}],
            })

        await say(blocks=blocks, text=summary)

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        logger.error("handle_dm failed for user %s: %s: %s", user_id, type(e).__name__, e)

        # 사용자 친화적 에러 메시지
        err_str = str(e)
        if "503" in err_str or "UNAVAILABLE" in err_str:
            msg = "⏳ AI 서비스가 일시적으로 과부하 상태입니다. 잠시 후 다시 시도해 주세요."
        elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            msg = "⏳ 요청이 너무 많아 일시적으로 제한되었습니다. 잠시 후 다시 시도해 주세요."
        elif "401" in err_str or "Unauthorized" in err_str:
            msg = "🔑 인증이 만료되었습니다. 계정을 다시 연결해 주세요."
        elif "timeout" in err_str.lower():
            msg = "⏱️ 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
        else:
            msg = f"⚠️ 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.\n(오류 코드: {type(e).__name__})"

        await say(msg)


# ---------------------------------------------------------------------------
# 프로젝트 기반 구조화 검색 핸들러
# ---------------------------------------------------------------------------

async def handle_project_search(
    user_id: str,
    project_names: list[str],
    category: str,
    date_from: str | None,
    date_to: str | None,
    say,
) -> None:
    """폼 기반 프로젝트 검색을 처리한다.

    흐름:
    1. 쿼리 변환 레이어로 플랫폼별 파라미터 생성
    2. 병렬로 Gmail/Drive/Confluence/Jira 검색
    3. AI 카테고리 필터링
    4. AI 요약 생성
    5. Slack 응답
    """
    try:
        category_info = CATEGORY_KEYWORDS.get(category, {})
        category_description = category_info.get("filter_description", "")

        async with AsyncSessionLocal() as db:
            # 사용자 계정 조회
            google_result = await db.execute(
                select(User).where(User.slack_user_id == user_id)
            )
            google_user = google_result.scalar_one_or_none()

            atlassian_result = await db.execute(
                select(AtlassianUser).where(AtlassianUser.slack_user_id == user_id)
            )
            atlassian_user = atlassian_result.scalar_one_or_none()

            if not google_user and not atlassian_user:
                await say("서비스 연결이 필요합니다. 먼저 계정을 연결해 주세요.")
                return

            # 연결된 서비스별 검색 태스크 빌드
            google_connected = False
            atlassian_connected = False
            tasks = []

            if google_user:
                try:
                    access_token = await get_valid_access_token(user=google_user, db=db)
                    google_connected = True

                    # Gmail: 프로젝트명 + 카테고리 보조 키워드로 검색
                    gmail_query = build_gmail_query(
                        project_names, category, date_from, date_to,
                    )
                    tasks.append(search_gmail(
                        access_token=access_token,
                        query=gmail_query,
                        max_results=50,
                    ))

                    # Drive: 프로젝트명으로 폴더 찾기 → 내부 파일 조회
                    tasks.append(search_drive_by_project(
                        access_token=access_token,
                        project_names=project_names,
                        max_results=50,
                        date_from=date_from,
                        date_to=date_to,
                    ))
                except Exception:
                    logger.exception("Google 토큰 획득 실패 (user_id=%s)", user_id)

            if atlassian_user:
                try:
                    atl_token, cloud_id = await get_valid_atlassian_token(
                        user=atlassian_user, db=db,
                    )
                    atlassian_connected = True

                    # Confluence: 프로젝트명 상위 페이지 → 하위 전체 조회
                    tasks.append(search_confluence_by_project(
                        atl_token, cloud_id, project_names,
                        max_results=50,
                        date_from=date_from,
                        date_to=date_to,
                    ))

                    # Jira: 프로젝트명으로 이슈 검색
                    tasks.append(search_jira_by_project(
                        atl_token, cloud_id, project_names,
                        max_results=50,
                        date_from=date_from,
                        date_to=date_to,
                    ))
                except AtlassianReauthRequired:
                    logger.warning("Atlassian 재인증 필요 (user_id=%s)", user_id)
                except Exception:
                    logger.exception("Atlassian 토큰 획득 실패 (user_id=%s)", user_id)

            if not tasks:
                await say("서비스 연결에 문제가 발생했습니다. 다시 인증해 주세요.")
                return

        # 병렬 검색 실행
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 예외 처리
        processed = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("프로젝트 검색 실패: %s", r)
                processed.append([])
            else:
                processed.append(r)

        # 결과 분배
        gmail_results, drive_results, confluence_results, jira_results = (
            _distribute_results(processed, google_connected, atlassian_connected)
        )

        project_label = ", ".join(project_names)
        print(
            f"[DEBUG] 프로젝트 검색 결과: Gmail={len(gmail_results)}건, "
            f"Drive={len(drive_results)}건, Confluence={len(confluence_results)}건, "
            f"Jira={len(jira_results)}건 (projects={project_label})"
        )

        # 필터링 전 문서 제목 로그
        for i, m in enumerate(gmail_results):
            print(f"[DEBUG] [필터전] Gmail[{i}]: {m.get('subject', '')}")
        for i, f in enumerate(drive_results):
            print(f"[DEBUG] [필터전] Drive[{i}]: {f.get('name', '')}")
        for i, c in enumerate(confluence_results):
            print(f"[DEBUG] [필터전] Confluence[{i}]: {c.get('title', '')}")
        for i, j in enumerate(jira_results):
            print(f"[DEBUG] [필터전] Jira[{i}]: [{j.get('key', '')}] {j.get('title', '')}")

        # AI 카테고리 필터링 (병렬)
        gmail_results, drive_results, confluence_results, jira_results = (
            await asyncio.gather(
                filter_by_category(category, category_description, gmail_results, "gmail"),
                filter_by_category(category, category_description, drive_results, "drive"),
                filter_by_category(category, category_description, confluence_results, "confluence"),
                filter_by_category(category, category_description, jira_results, "jira"),
            )
        )

        print(
            f"[DEBUG] 카테고리 필터링 후: Gmail={len(gmail_results)}건, "
            f"Drive={len(drive_results)}건, Confluence={len(confluence_results)}건, "
            f"Jira={len(jira_results)}건 (category={category})"
        )

        for i, m in enumerate(gmail_results):
            print(f"[DEBUG] [필터후] Gmail[{i}]: {m.get('subject', '')}")
        for i, f in enumerate(drive_results):
            print(f"[DEBUG] [필터후] Drive[{i}]: {f.get('name', '')}")
        for i, c in enumerate(confluence_results):
            print(f"[DEBUG] [필터후] Confluence[{i}]: {c.get('title', '')}")
        for i, j in enumerate(jira_results):
            print(f"[DEBUG] [필터후] Jira[{i}]: [{j.get('key', '')}] {j.get('title', '')}")

        total = (
            len(gmail_results) + len(drive_results)
            + len(confluence_results) + len(jira_results)
        )
        if total == 0:
            await say(
                f"'{project_label}' ({category}) 관련 검색 결과를 찾지 못했습니다. "
                f"다른 프로젝트명이나 카테고리로 검색해 보세요."
            )
            return

        # AI 요약 생성
        question = f"{project_label} 프로젝트의 {category_description}"
        summary = await summarize_results(
            question=question,
            gmail_results=gmail_results,
            drive_results=drive_results,
            confluence_results=confluence_results,
            jira_results=jira_results,
            user_id=user_id,
        )

        # Block Kit 포맷팅
        blocks = format_search_response(
            summary_text=summary,
            gmail_results=gmail_results,
            drive_results=drive_results,
            confluence_results=confluence_results,
            jira_results=jira_results,
            connect_google=not google_connected,
            connect_atlassian=not atlassian_connected,
        )

        # 날짜 필터 배너
        if date_from or date_to:
            date_banner = "📅 "
            if date_from and date_to:
                date_banner += f"{date_from} ~ {date_to} 기간으로 검색했습니다"
            elif date_from:
                date_banner += f"{date_from} 이후로 검색했습니다"
            else:
                date_banner += f"{date_to} 이전으로 검색했습니다"
            blocks.insert(0, {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": date_banner}],
            })

        await say(blocks=blocks, text=summary)

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        logger.error(
            "handle_project_search failed for user %s: %s: %s",
            user_id, type(e).__name__, e,
        )
        await say("⚠️ 프로젝트 검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
