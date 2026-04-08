"""엔티티 검색 메인 핸들러 모듈.

사용자가 특정 엔티티(고객사, 담당자, 프로젝트, 팀)를 중심으로
Gmail, Drive, Confluence, Jira 전체를 한 번에 검색하고
시간순 타임라인으로 결과를 확인할 수 있게 한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.atlassian_user import AtlassianUser
from app.google.gmail import search_gmail
from app.google.drive import search_drive
from app.google.token_refresh import get_valid_access_token
from app.atlassian.token_refresh import get_valid_atlassian_token, AtlassianReauthRequired
from app.atlassian.confluence import search_confluence
from app.atlassian.jira import search_jira
from app.ai.summarizer import summarize_entity_results
from app.search.result_grouper import group_results
from app.slack.block_kit import (
    format_entity_candidates,
    format_entity_timeline,
    format_similar_entities,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Claude client (reuse pattern from summarizer.py)
# ---------------------------------------------------------------------------

import anthropic
from app.config import settings

_claude_client: anthropic.AsyncAnthropic | None = None


def _get_claude_client() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _claude_client


# ---------------------------------------------------------------------------
# handle_entity_search
# ---------------------------------------------------------------------------


async def handle_entity_search(
    user_id: str,
    entities: list[dict],
    original_text: str,
    say,
) -> None:
    """엔티티 검색 메인 핸들러.

    1. 엔티티 후보가 2개 이상이면 Slack 버튼으로 선택 요청
    2. 엔티티 후보가 1개이면 즉시 검색 수행
    """
    if len(entities) >= 2:
        # 후보 목록을 Slack 버튼으로 표시
        blocks = format_entity_candidates(entities, original_text)
        await say(blocks=blocks, text="엔티티를 선택해 주세요.")
        return

    # 엔티티가 정확히 1개 → 즉시 검색
    entity = entities[0]
    await execute_entity_search(
        user_id=user_id,
        entity_name=entity["name"],
        entity_type=entity["type"],
        say=say,
    )


# ---------------------------------------------------------------------------
# execute_entity_search
# ---------------------------------------------------------------------------

_SIX_MONTHS_AGO_FACTORY = lambda: datetime.now(timezone.utc) - timedelta(days=180)


def _filter_recent_results(
    results: list[dict],
    date_key: str,
    cutoff: datetime,
) -> list[dict]:
    """날짜 필드 기준으로 cutoff 이후의 결과만 반환한다."""
    filtered: list[dict] = []
    for r in results:
        raw_date = r.get(date_key, "")
        if not raw_date:
            # 날짜 없는 항목은 포함
            filtered.append(r)
            continue
        try:
            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if dt >= cutoff:
                filtered.append(r)
        except (ValueError, TypeError):
            filtered.append(r)
    return filtered


async def execute_entity_search(
    user_id: str,
    entity_name: str,
    entity_type: str,
    say,
) -> None:
    """확정된 엔티티로 실제 검색을 수행한다.

    - DB에서 사용자 토큰 조회 (기존 handle_dm 패턴 재사용)
    - 4개 플랫폼 asyncio.gather 병렬 검색
    - 개별 플랫폼 오류 시 빈 리스트 + logger.exception() 로깅
    - 100건 초과 시 최근 6개월 자동 필터링 + 안내 메시지
    - 결과 0건 시 find_similar_entities → 유사 엔티티 추천 또는 안내 메시지
    - 결과 존재 시 group_results → summarize_entity_results → format_entity_timeline → say 출력
    """
    await say(f"🔍 *{entity_name}* ({entity_type}) 관련 정보를 검색 중입니다...")

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

        # 연결된 서비스에 대해 토큰 획득 및 검색 태스크 빌드
        google_connected = False
        atlassian_connected = False
        tasks: list = []

        if google_user:
            try:
                access_token = await get_valid_access_token(user=google_user, db=db)
                google_connected = True
                tasks.append(search_gmail(access_token=access_token, query=entity_name, max_results=50))
                tasks.append(search_drive(access_token=access_token, query=entity_name, max_results=50))
            except Exception:
                logger.exception("Google 토큰 획득 실패 (user_id=%s)", user_id)

        if atlassian_user:
            try:
                atl_token, cloud_id = await get_valid_atlassian_token(user=atlassian_user, db=db)
                atlassian_connected = True
                tasks.append(search_confluence(atl_token, cloud_id, entity_name, max_results=50))
                tasks.append(search_jira(atl_token, cloud_id, entity_name, max_results=50))
            except AtlassianReauthRequired:
                logger.warning("Atlassian 재인증 필요 (user_id=%s)", user_id)
            except Exception:
                logger.exception("Atlassian 토큰 획득 실패 (user_id=%s)", user_id)

        if not tasks:
            await say("서비스 연결에 문제가 발생했습니다. 다시 인증해 주세요.")
            return

    # 병렬 검색 실행
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 예외 처리: Exception → 빈 리스트 + 로깅
    processed: list[list] = []
    for r in results:
        if isinstance(r, Exception):
            logger.exception("플랫폼 검색 실패: %s", r)
            processed.append([])
        else:
            processed.append(r)

    # 결과 분배
    idx = 0
    gmail_results: list = []
    drive_results: list = []
    confluence_results: list = []
    jira_results: list = []

    if google_connected:
        gmail_results = processed[idx]; idx += 1
        drive_results = processed[idx]; idx += 1
    if atlassian_connected:
        confluence_results = processed[idx]; idx += 1
        jira_results = processed[idx]; idx += 1

    total_count = len(gmail_results) + len(drive_results) + len(confluence_results) + len(jira_results)

    # 100건 초과 시 최근 6개월 자동 필터링
    filtered = False
    if total_count > 100:
        cutoff = _SIX_MONTHS_AGO_FACTORY()
        gmail_results = _filter_recent_results(gmail_results, "date", cutoff)
        drive_results = _filter_recent_results(drive_results, "modified", cutoff)
        confluence_results = _filter_recent_results(confluence_results, "modified", cutoff)
        jira_results = _filter_recent_results(jira_results, "updated", cutoff)
        filtered = True
        await say(f"📋 검색 결과가 {total_count}건으로 많아 최근 6개월 이내 결과로 필터링했습니다.")

    new_total = len(gmail_results) + len(drive_results) + len(confluence_results) + len(jira_results)

    # 결과 0건 → 유사 엔티티 추천
    if new_total == 0:
        similar = await find_similar_entities(entity_name, [])
        if similar:
            blocks = format_similar_entities(similar)
            await say(
                blocks=blocks,
                text=f"'{entity_name}'에 대한 검색 결과가 없습니다. 유사한 엔티티를 추천합니다.",
            )
        else:
            await say(f"관련 엔티티를 찾을 수 없습니다. 다른 이름으로 검색해 주세요.")
        return

    # 결과 그룹핑
    grouped = group_results(
        gmail_results=gmail_results,
        drive_results=drive_results,
        confluence_results=confluence_results,
        jira_results=jira_results,
        filtered=filtered,
    )

    # AI 요약 생성
    summary = await summarize_entity_results(
        entity_name=entity_name,
        entity_type=entity_type,
        gmail_results=gmail_results,
        drive_results=drive_results,
        confluence_results=confluence_results,
        jira_results=jira_results,
    )

    # Block Kit 포맷팅 및 출력
    blocks = format_entity_timeline(
        entity_name=entity_name,
        entity_type=entity_type,
        summary_text=summary,
        grouped_results=grouped,
    )

    await say(blocks=blocks, text=summary)


# ---------------------------------------------------------------------------
# find_similar_entities
# ---------------------------------------------------------------------------

_SIMILAR_ENTITIES_PROMPT = """\
사용자가 "{query}" 엔티티를 검색했지만 결과가 없습니다.
아래 검색 결과에서 "{query}"와 유사한 엔티티(고객사, 담당자, 프로젝트, 팀) 이름을 추출해 주세요.

규칙:
- 최대 5개까지만 추천
- 각 엔티티에 name(이름)과 type(고객사/담당자/프로젝트/팀)을 포함
- 유사한 엔티티가 없으면 빈 배열 반환
- 반드시 JSON 배열로만 응답하세요

응답 형식:
[{{"name": "엔티티명", "type": "고객사|담당자|프로젝트|팀"}}]
"""


async def find_similar_entities(
    query: str,
    all_results: list[dict],
) -> list[dict]:
    """검색 결과가 0건일 때 유사 엔티티를 추천한다.

    - Gemini AI를 활용하여 유사 엔티티 추출
    - 최대 5개까지 추천
    """
    try:
        claude = _get_claude_client()

        context = ""
        if all_results:
            context = "\n".join(
                f"- {r.get('title', r.get('subject', r.get('name', '')))}"
                for r in all_results[:50]
            )
        else:
            context = "(검색 결과 없음)"

        prompt = _SIMILAR_ENTITIES_PROMPT.format(query=query) + f"\n\n[검색 결과]\n{context}"

        print("[DEBUG] [AI] 유사 엔티티 추출: Claude (claude-sonnet-4-20250514)")
        response = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system="반드시 JSON만 출력하세요. 다른 텍스트 없이 JSON만 출력하세요.",
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []

        # Validate and limit to 5
        valid: list[dict] = []
        for item in parsed:
            if isinstance(item, dict) and item.get("name") and item.get("type"):
                valid.append({"name": item["name"], "type": item["type"]})
            if len(valid) >= 5:
                break

        return valid

    except Exception:
        logger.exception("유사 엔티티 추출 실패 (query=%s)", query)
        return []
