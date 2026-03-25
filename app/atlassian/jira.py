import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_JIRA_SEARCH_URL = (
    "https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql"
)

# cloud_id → site_url 캐시 (서버 재시작 시 초기화)
_site_url_cache: dict[str, str] = {}


async def _get_site_url(access_token: str, cloud_id: str) -> str | None:
    """cloud_id에 해당하는 Atlassian 사이트 URL을 조회한다."""
    if cloud_id in _site_url_cache:
        return _site_url_cache[cloud_id]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            resp.raise_for_status()

        for site in resp.json():
            if site.get("id") == cloud_id:
                url = site.get("url", "").rstrip("/")
                if url:
                    _site_url_cache[cloud_id] = url
                    return url
    except Exception:
        logger.warning("Atlassian site URL 조회 실패 (cloud_id=%s)", cloud_id)

    return None


def _extract_base_url(self_link: str) -> str:
    """이슈의 self 필드에서 사이트 base URL을 추출한다.

    예: "https://your-site.atlassian.net/rest/api/3/issue/10001"
        → "https://your-site.atlassian.net"
    """
    parsed = urlparse(self_link)
    return f"{parsed.scheme}://{parsed.netloc}"


async def search_jira(
    access_token: str,
    cloud_id: str,
    query: str,
    max_results: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """JQL로 Jira 이슈를 검색한다.

    Returns:
        각 이슈의 {key, title, status, assignee, priority, link}
        딕셔너리 리스트. API 실패 시 빈 리스트를 반환한다.
    """
    try:
        url = _JIRA_SEARCH_URL.format(cloud_id=cloud_id)
        # 쉼표가 있으면 OR 검색, 없으면 AND (단일 쿼리)
        if "," in query:
            parts = [p.strip() for p in query.split(",") if p.strip()]
            summary_parts = " OR ".join(f'summary ~ "{p}"' for p in parts)
            desc_parts = " OR ".join(f'description ~ "{p}"' for p in parts)
            jql = f'({summary_parts} OR {desc_parts})'
        else:
            jql = f'(summary ~ "{query}" OR description ~ "{query}")'

        # 날짜 필터 적용 (Jira: updated >= "YYYY-MM-DD")
        if date_from:
            jql += f' AND updated >= "{date_from}"'
        if date_to:
            jql += f' AND updated <= "{date_to}"'

        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,assignee,priority,updated",
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # 사이트 URL 조회 (browse 링크 생성용)
        site_url = await _get_site_url(access_token, cloud_id)

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        results: list[dict] = []

        for issue in data.get("issues", []):
            key = issue.get("key", "")
            fields = issue.get("fields", {})

            title = fields.get("summary", "")
            status = (fields.get("status") or {}).get("name", "")
            assignee = (fields.get("assignee") or {}).get("displayName", "미지정")
            priority = (fields.get("priority") or {}).get("name", "")

            # link: site_url 우선, fallback으로 self 필드에서 추출
            if site_url and key:
                link = f"{site_url}/browse/{key}"
            else:
                self_link = issue.get("self", "")
                if self_link and key:
                    base_url = _extract_base_url(self_link)
                    link = f"{base_url}/browse/{key}"
                else:
                    link = ""

            results.append(
                {
                    "key": key,
                    "title": title,
                    "status": status,
                    "assignee": assignee,
                    "priority": priority,
                    "updated": fields.get("updated", ""),
                    "link": link,
                }
            )

        return results

    except Exception:
        logger.exception("Jira 검색 실패 (cloud_id=%s, query=%s)", cloud_id, query)
        return []
