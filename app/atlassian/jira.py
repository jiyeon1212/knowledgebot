import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_JIRA_SEARCH_URL = (
    "https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql"
)


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
) -> list[dict]:
    """JQL로 Jira 이슈를 검색한다.

    Returns:
        각 이슈의 {key, title, status, assignee, priority, link}
        딕셔너리 리스트. API 실패 시 빈 리스트를 반환한다.
    """
    try:
        url = _JIRA_SEARCH_URL.format(cloud_id=cloud_id)
        params = {
            "jql": f'(summary ~ "{query}" OR description ~ "{query}") ORDER BY updated DESC',
            "maxResults": max_results,
            "fields": "summary,status,assignee,priority,updated",
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

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

            # link: self 필드에서 base URL 추출 후 /browse/{key} 추가
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
