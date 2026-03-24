"""검색 결과 그룹핑 및 타임라인 생성 모듈.

4개 플랫폼(Gmail, Drive, Confluence, Jira) 검색 결과를 통합하고
시간순 정렬, 미결 이슈 추출, 담당자 목록 추출 기능을 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypedDict


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TimelineItem:
    """타임라인 항목."""

    date: str  # ISO 8601 날짜
    title: str
    source: str  # "gmail" | "drive" | "confluence" | "jira"
    summary: str
    link: str
    metadata: dict = field(default_factory=dict)


@dataclass
class GroupedResults:
    """그룹핑된 검색 결과."""

    timeline: list[TimelineItem]
    open_issues: list[TimelineItem]
    contacts: list[str]
    total_count: int
    filtered: bool


class EntityInfo(TypedDict):
    """AI가 추출한 엔티티 정보."""

    name: str  # 엔티티명
    type: str  # "고객사" | "담당자" | "프로젝트" | "팀"


class IntentResult(TypedDict, total=False):
    """확장된 의도 분류 결과."""

    intent: str  # "search" | "chat" | "entity_search"
    search_keyword: str | None
    max_results: int | None
    entities: list[EntityInfo] | None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_ICONS: dict[str, str] = {
    "gmail": "📧",
    "drive": "📁",
    "confluence": "📄",
    "jira": "🎫",
}


# ---------------------------------------------------------------------------
# Helper: epoch ms → ISO 8601
# ---------------------------------------------------------------------------

def _epoch_ms_to_iso(epoch_ms: str) -> str:
    """Gmail의 epoch milliseconds 문자열을 ISO 8601 문자열로 변환한다.

    빈 문자열이나 변환 불가능한 값은 빈 문자열을 반환한다.
    """
    if not epoch_ms:
        return ""
    try:
        ts = int(epoch_ms) / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return ""


# ---------------------------------------------------------------------------
# normalize_results
# ---------------------------------------------------------------------------

def normalize_results(
    gmail_results: list[dict],
    drive_results: list[dict],
    confluence_results: list[dict],
    jira_results: list[dict],
) -> list[TimelineItem]:
    """4개 플랫폼의 검색 결과를 TimelineItem 리스트로 통합한다."""
    items: list[TimelineItem] = []

    # Gmail: date(epoch ms → ISO), subject → title, content_summary → summary, link
    for r in gmail_results:
        items.append(
            TimelineItem(
                date=_epoch_ms_to_iso(r.get("date", "")),
                title=r.get("subject", ""),
                source="gmail",
                summary=r.get("content_summary", ""),
                link=r.get("link", ""),
                metadata={"from": r.get("from", "")},
            )
        )

    # Drive: modified → date, name → title, link
    for r in drive_results:
        items.append(
            TimelineItem(
                date=r.get("modified", ""),
                title=r.get("name", ""),
                source="drive",
                summary="",
                link=r.get("link", ""),
                metadata={"mime_type": r.get("mime_type", "")},
            )
        )

    # Confluence: modified → date, title, content_summary → summary, link, space_name → metadata
    for r in confluence_results:
        items.append(
            TimelineItem(
                date=r.get("modified", ""),
                title=r.get("title", ""),
                source="confluence",
                summary=r.get("content_summary", ""),
                link=r.get("link", ""),
                metadata={"space_name": r.get("space_name", "")},
            )
        )

    # Jira: updated → date, title, key/status/assignee/priority → metadata, link
    for r in jira_results:
        items.append(
            TimelineItem(
                date=r.get("updated", ""),
                title=r.get("title", ""),
                source="jira",
                summary="",
                link=r.get("link", ""),
                metadata={
                    "key": r.get("key", ""),
                    "status": r.get("status", ""),
                    "assignee": r.get("assignee", ""),
                    "priority": r.get("priority", ""),
                },
            )
        )

    return items


# ---------------------------------------------------------------------------
# sort_by_date
# ---------------------------------------------------------------------------

def sort_by_date(
    items: list[TimelineItem],
    descending: bool = True,
) -> list[TimelineItem]:
    """TimelineItem 리스트를 ISO 8601 날짜 기준으로 정렬한다.

    빈 날짜 문자열은 가장 오래된 것으로 취급한다.
    """
    return sorted(items, key=lambda item: item.date or "", reverse=descending)


# ---------------------------------------------------------------------------
# extract_open_issues
# ---------------------------------------------------------------------------

_DONE_STATUSES = frozenset({"완료", "done"})


def extract_open_issues(items: list[TimelineItem]) -> list[TimelineItem]:
    """Jira 결과 중 상태가 '완료'/'done'이 아닌 이슈를 추출한다."""
    return [
        item
        for item in items
        if item.source == "jira"
        and item.metadata.get("status", "").lower() not in _DONE_STATUSES
    ]


# ---------------------------------------------------------------------------
# extract_contacts
# ---------------------------------------------------------------------------

def extract_contacts(items: list[TimelineItem]) -> list[str]:
    """검색 결과에서 관련 담당자 목록을 추출한다 (중복 제거).

    - Gmail: metadata["from"] 에서 발신자
    - Jira: metadata["assignee"] 에서 담당자
    """
    contacts: list[str] = []
    seen: set[str] = set()

    for item in items:
        names: list[str] = []
        if item.source == "gmail":
            sender = item.metadata.get("from", "")
            if sender:
                names.append(sender)
        elif item.source == "jira":
            assignee = item.metadata.get("assignee", "")
            if assignee and assignee != "미지정":
                names.append(assignee)

        for name in names:
            if name not in seen:
                seen.add(name)
                contacts.append(name)

    return contacts


# ---------------------------------------------------------------------------
# group_results
# ---------------------------------------------------------------------------

def group_results(
    gmail_results: list[dict],
    drive_results: list[dict],
    confluence_results: list[dict],
    jira_results: list[dict],
    filtered: bool = False,
) -> GroupedResults:
    """검색 결과를 그룹핑하여 GroupedResults를 반환한다."""
    all_items = normalize_results(
        gmail_results, drive_results, confluence_results, jira_results
    )
    timeline = sort_by_date(all_items)
    open_issues = extract_open_issues(all_items)
    contacts = extract_contacts(all_items)

    return GroupedResults(
        timeline=timeline,
        open_issues=open_issues,
        contacts=contacts,
        total_count=len(all_items),
        filtered=filtered,
    )
