import asyncio
import logging
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
from app.google.drive import search_drive
from app.google.token_refresh import get_valid_access_token
from app.atlassian.token_refresh import get_valid_atlassian_token, AtlassianReauthRequired
from app.atlassian.confluence import search_confluence
from app.atlassian.jira import search_jira
from app.ai.summarizer import classify_intent, generate_chat_response, summarize_results, filter_irrelevant_results
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
        # 1. 의도 분류
        intent_result = await classify_intent(text)
        intent = intent_result["intent"]

        # 2. chat 의도 → AI 직접 답변
        if intent == "chat":
            response = await generate_chat_response(text)
            await say(response)
            return

        # 3. search 의도 → 검색 흐름
        keyword = intent_result.get("search_keyword") or text
        max_results = intent_result.get("max_results") or 50

        # AI가 추출한 키워드에 원문의 핵심 단어가 빠졌는지 검증
        # 원문 단어 중 keyword에 없는 고유명사(영문, 한글 2자 이상)를 보충
        if keyword != text:
            original_words = text.split()
            keyword_lower = keyword.lower()
            missing = []
            _STOP_WORDS = {"관련", "관련해서", "찾아줘", "검색해줘", "보여줘", "알려줘",
                           "현재", "진행", "내용", "자료", "문서", "히스토리", "관련된",
                           "해줘", "좀", "에", "대해", "대한", "의", "을", "를", "이", "가",
                           "은", "는", "로", "으로", "에서", "와", "과", "도", "만", "까지"}
            for w in original_words:
                w_clean = w.strip(".,!?~")
                if not w_clean:
                    continue
                if w_clean.lower() in _STOP_WORDS:
                    continue
                if w_clean.lower() not in keyword_lower:
                    missing.append(w_clean)
            if missing:
                keyword = " ".join(missing) + " " + keyword
                logger.info("키워드 보충: %s (원문에서 누락된 단어: %s)", keyword, missing)

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
                    tasks.append(search_gmail(access_token=access_token, query=keyword, max_results=max_results))
                    tasks.append(search_drive(access_token=access_token, query=keyword, max_results=max_results))
                except Exception:
                    logger.exception("Google 토큰 획득 실패 (user_id=%s)", user_id)

            if atlassian_user:
                try:
                    atl_token, cloud_id = await get_valid_atlassian_token(user=atlassian_user, db=db)
                    atlassian_connected = True
                    tasks.append(search_confluence(atl_token, cloud_id, keyword, max_results=max_results))
                    tasks.append(search_jira(atl_token, cloud_id, keyword, max_results=max_results))
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
