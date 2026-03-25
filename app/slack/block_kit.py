"""Block Kit Formatter — 검색 결과와 AI 요약을 Slack Block Kit JSON으로 변환한다."""

from datetime import datetime, timezone, timedelta

_KST = timezone(timedelta(hours=9))


def _format_date(raw: str) -> str:
    """날짜 문자열을 '2024.08.26' 형식으로 변환한다.

    지원 형식:
    - ISO 8601 (예: "2024-08-26T10:00:00Z")
    - epoch milliseconds (예: "1773978410000") — Gmail internalDate
    """
    if not raw:
        return ""
    try:
        raw = str(raw).strip()
        # epoch milliseconds (숫자로만 구성된 13자리 이상)
        if raw.isdigit() and len(raw) >= 13:
            dt = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
            return dt.astimezone(_KST).strftime("%Y.%m.%d")
        # ISO 8601
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(_KST).strftime("%Y.%m.%d")
    except (ValueError, TypeError, OSError):
        return raw


def format_search_response(
    summary_text: str,
    gmail_results: list[dict],
    drive_results: list[dict],
    confluence_results: list[dict],
    jira_results: list[dict],
    connect_google: bool = False,
    connect_atlassian: bool = False,
    google_auth_url: str | None = None,
    atlassian_auth_url: str | None = None,
) -> list[dict]:
    """검색 결과와 요약을 Block Kit JSON으로 변환한다.

    Parameters:
        summary_text: AI가 생성한 요약 텍스트
        gmail_results: Gmail 검색 결과 리스트
        drive_results: Drive 검색 결과 리스트
        confluence_results: Confluence 검색 결과 리스트
        jira_results: Jira 검색 결과 리스트
        connect_google: Google 연결 안내 버튼 표시 여부
        connect_atlassian: Atlassian 연결 안내 버튼 표시 여부
        google_auth_url: Google OAuth 인증 URL
        atlassian_auth_url: Atlassian OAuth 인증 URL

    Returns:
        Slack Block Kit blocks 배열
    """
    blocks: list[dict] = []

    # 1. AI 요약 텍스트
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "🤖 *AI 요약*"},
    })

    _MAX_SECTION_TEXT = 2900  # Slack 제한 3000자, 여유분 확보
    if len(summary_text) <= _MAX_SECTION_TEXT:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary_text},
        })
    else:
        # 긴 요약은 여러 section 블록으로 분할
        remaining = summary_text
        while remaining:
            chunk = remaining[:_MAX_SECTION_TEXT]
            remaining = remaining[_MAX_SECTION_TEXT:]
            if remaining and "\n" in chunk[_MAX_SECTION_TEXT // 2:]:
                split_pos = chunk.rfind("\n")
                remaining = chunk[split_pos:] + remaining
                chunk = chunk[:split_pos]
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            })

    # 2. 소스별 검색 결과 섹션 (0건이어도 표시, 각 소스 최대 5건)
    _MAX_ITEMS_PER_SOURCE = 5

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"📧 *Gmail 검색 결과 ({len(gmail_results)}건)*",
        },
    })
    for item in gmail_results[:_MAX_ITEMS_PER_SOURCE]:
        blocks.append(_gmail_block(item))

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"📁 *Drive 검색 결과 ({len(drive_results)}건)*",
        },
    })
    for item in drive_results[:_MAX_ITEMS_PER_SOURCE]:
        blocks.append(_drive_block(item))

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"📄 *Confluence 검색 결과 ({len(confluence_results)}건)*",
        },
    })
    for item in confluence_results[:_MAX_ITEMS_PER_SOURCE]:
        blocks.append(_confluence_block(item))

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"🎫 *Jira 검색 결과 ({len(jira_results)}건)*",
        },
    })
    for item in jira_results[:_MAX_ITEMS_PER_SOURCE]:
        blocks.append(_jira_block(item))

    # 3. 미연결 서비스 연결 안내 버튼
    if connect_google and google_auth_url:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔗 Google 계정 연결하기"},
                    "url": google_auth_url,
                    "action_id": "google_oauth_login",
                },
            ],
        })

    if connect_atlassian and atlassian_auth_url:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔗 Atlassian 계정 연결하기"},
                    "url": atlassian_auth_url,
                    "action_id": "atlassian_oauth_login",
                },
            ],
        })

    # Slack Block Kit 50블록 제한 안전장치
    return blocks[:50]


# ---------------------------------------------------------------------------
# Jira 상태 이모지 매핑
# ---------------------------------------------------------------------------

_JIRA_STATUS_EMOJI: dict[str, str] = {
    "완료": "🟢",
    "done": "🟢",
    "진행중": "🟡",
    "진행 중": "🟡",
    "in progress": "🟡",
    "할일": "🔴",
    "할 일": "🔴",
    "to do": "🔴",
}


def _jira_status_emoji(status: str) -> str:
    """Jira 상태 문자열에 대응하는 이모지를 반환한다."""
    return _JIRA_STATUS_EMOJI.get(status.lower().strip(), "⚪")


# ---------------------------------------------------------------------------
# 소스별 블록 생성 헬퍼
# ---------------------------------------------------------------------------


def _make_link_button(text: str, url: str) -> dict:
    """Slack Block Kit 링크 버튼 요소를 생성한다."""
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "url": url,
    }


def _gmail_block(item: dict) -> dict:
    subject = item.get("subject", "(제목 없음)")
    sender = item.get("from", "")
    date = _format_date(item.get("date", ""))
    link = item.get("link", "")

    lines = [f"*{subject}*"]
    lines.append(f"보낸이: {sender}")
    if date:
        lines.append(f"수신일: {date}")

    block: dict = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }
    if link:
        block["accessory"] = _make_link_button("메일 열기", link)
    return block


def _drive_block(item: dict) -> dict:
    name = item.get("name", "(이름 없음)")
    modified = _format_date(item.get("modified", ""))
    link = item.get("link", "")

    lines = [f"*{name}*"]
    if modified:
        lines.append(f"수정일: {modified}")

    block: dict = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }
    if link:
        block["accessory"] = _make_link_button("파일 열기", link)
    return block


def _confluence_block(item: dict) -> dict:
    title = item.get("title", "(제목 없음)")
    modified = _format_date(item.get("modified", ""))
    link = item.get("link", "")

    lines = [f"*{title}*"]
    if modified:
        lines.append(f"수정일: {modified}")

    block: dict = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }
    if link:
        block["accessory"] = _make_link_button("페이지 열기", link)
    return block


def _jira_block(item: dict) -> dict:
    key = item.get("key", "")
    title = item.get("title", "(제목 없음)")
    assignee = item.get("assignee", "")
    link = item.get("link", "")

    header = f"*[{key}] {title}*" if key else f"*{title}*"
    lines = [header]
    if assignee:
        lines.append(f"담당자: {assignee}")

    block: dict = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }
    if link:
        block["accessory"] = _make_link_button("이슈 열기", link)
    return block


# ---------------------------------------------------------------------------
# 엔티티 검색 관련 포맷 함수 (Task 8에서 본격 구현 예정)
# ---------------------------------------------------------------------------


def format_entity_timeline(
    entity_name: str,
    entity_type: str,
    summary_text: str,
    grouped_results,
) -> list[dict]:
    """엔티티 타임라인을 Block Kit JSON으로 변환한다.

    TODO: Task 8에서 본격 구현 예정.
    """
    raise NotImplementedError("format_entity_timeline은 Task 8에서 구현 예정입니다.")


def format_entity_candidates(
    candidates: list[dict],
    original_query: str,
) -> list[dict]:
    """엔티티 후보 목록을 Slack 버튼으로 포맷팅한다.

    TODO: Task 8에서 본격 구현 예정.
    """
    raise NotImplementedError("format_entity_candidates는 Task 8에서 구현 예정입니다.")


def format_similar_entities(
    suggestions: list[dict],
) -> list[dict]:
    """유사 엔티티 추천 목록을 Slack 버튼으로 포맷팅한다.

    TODO: Task 8에서 본격 구현 예정.
    """
    raise NotImplementedError("format_similar_entities는 Task 8에서 구현 예정입니다.")
