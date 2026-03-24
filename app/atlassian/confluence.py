import logging
import re

import httpx

logger = logging.getLogger(__name__)

_CONFLUENCE_SEARCH_URL = (
    "https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/search"
)

_TAG_RE = re.compile(r"<[^>]+>")
_HIGHLIGHT_RE = re.compile(r"@@@(?:end)?hl@@@")


def _strip_html(html: str) -> str:
    """HTML 태그와 Confluence 하이라이트 마커를 제거하고 텍스트만 반환한다."""
    text = _TAG_RE.sub("", html)
    text = _HIGHLIGHT_RE.sub("", text)
    # 연속 공백/줄바꿈을 단일 공백으로 정리
    return " ".join(text.split())


def _truncate(text: str, max_length: int = 200) -> str:
    """텍스트를 max_length 이하로 잘라 반환한다."""
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(" ", 1)[0] + "…"


async def search_confluence(
    access_token: str,
    cloud_id: str,
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """CQL로 Confluence 페이지를 검색한다.

    Returns:
        각 페이지의 {title, space_name, excerpt, content_summary, modified, link}
        딕셔너리 리스트. API 실패 시 빈 리스트를 반환한다.
    """
    try:
        url = _CONFLUENCE_SEARCH_URL.format(cloud_id=cloud_id)
        params = {
            "cql": f'type=page AND text~"{query}" order by lastModified desc',
            "limit": max_results,
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

        for item in data.get("results", []):
            content = item.get("content", item)
            title = content.get("title", "") or item.get("title", "")
            space_name = content.get("space", {}).get("name", "") if "space" in content else ""
            excerpt = item.get("excerpt", "")

            # 하이라이트 마커 및 HTML 태그 제거
            clean_excerpt = _truncate(_strip_html(excerpt)) if excerpt else ""

            # content_summary: excerpt에서 HTML 태그 제거 후 ~200자로 잘라냄
            content_summary = clean_excerpt

            # modified: lastModified 또는 version.when
            modified = item.get("lastModified", "") or content.get("version", {}).get("when", "")

            # link: _links.base + webui
            base_url = data.get("_links", {}).get("base", "")
            web_path = item.get("url", "") or content.get("_links", {}).get("webui", "")
            link = f"{base_url}{web_path}" if base_url and web_path else ""

            results.append(
                {
                    "title": title,
                    "space_name": space_name,
                    "excerpt": clean_excerpt,
                    "content_summary": content_summary,
                    "modified": modified,
                    "link": link,
                }
            )

        return results

    except Exception:
        logger.exception("Confluence 검색 실패 (cloud_id=%s, query=%s)", cloud_id, query)
        return []
