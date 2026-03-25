import logging
import re

import httpx

logger = logging.getLogger(__name__)

_CONFLUENCE_SEARCH_URL = (
    "https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/search"
)

_TAG_RE = re.compile(r"<[^>]+>")
_HIGHLIGHT_RE = re.compile(r"@@@(?:end)?hl@@@")

# cloud_id → site_url 캐시 (jira.py와 공유하지 않으므로 별도 관리)
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
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """CQL로 Confluence 페이지를 검색한다.

    1단계: text~"query"로 본문/제목 검색
    2단계: title~"query"로 상위 페이지를 찾고, 그 하위 페이지도 가져옴

    Returns:
        각 페이지의 {title, space_name, excerpt, content_summary, modified, link}
        딕셔너리 리스트. API 실패 시 빈 리스트를 반환한다.
    """
    try:
        url = _CONFLUENCE_SEARCH_URL.format(cloud_id=cloud_id)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # 사이트 URL 조회 (browse 링크 생성용)
        site_url = await _get_site_url(access_token, cloud_id)

        seen_ids: set[str] = set()
        results: list[dict] = []

        async with httpx.AsyncClient() as client:
            # 쉼표가 있으면 OR 검색, 없으면 AND (단일 text~ 쿼리)
            if "," in query:
                parts = [p.strip() for p in query.split(",") if p.strip()]
                text_cql = " OR ".join(f'text~"{p}"' for p in parts)
                title_cql = " OR ".join(f'title~"{p}"' for p in parts)
            else:
                text_cql = f'text~"{query}"'
                title_cql = f'title~"{query}"'

            # 날짜 필터 CQL 조건
            date_cql = ""
            if date_from:
                date_cql += f' AND lastModified >= "{date_from}"'
            if date_to:
                date_cql += f' AND lastModified <= "{date_to}"'

            # 1단계: 본문/제목 텍스트 검색
            resp = await client.get(
                url,
                params={
                    "cql": f'type=page AND ({text_cql}){date_cql}',
                    "limit": max_results,
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
                parsed = _parse_confluence_item(item, data, site_url)
                if parsed and parsed["id"] not in seen_ids:
                    seen_ids.add(parsed["id"])
                    results.append(parsed)

            # 2단계: 제목에 키워드가 포함된 페이지의 하위 페이지 검색
            ancestor_resp = await client.get(
                url,
                params={
                    "cql": f'type=page AND ({title_cql})',
                    "limit": 5,
                },
                headers=headers,
            )
            ancestor_resp.raise_for_status()
            ancestor_data = ancestor_resp.json()

            ancestor_ids = []
            for item in ancestor_data.get("results", []):
                content = item.get("content", item)
                page_id = str(content.get("id", ""))
                if page_id:
                    ancestor_ids.append(page_id)
                    # 상위 페이지 자체도 결과에 포함
                    parsed = _parse_confluence_item(item, ancestor_data, site_url)
                    if parsed and parsed["id"] not in seen_ids:
                        seen_ids.add(parsed["id"])
                        results.append(parsed)

            # 각 ancestor의 하위 페이지 검색
            for ancestor_id in ancestor_ids:
                child_resp = await client.get(
                    url,
                    params={
                        "cql": f'type=page AND ancestor={ancestor_id}{date_cql}',
                        "limit": max_results,
                    },
                    headers=headers,
                )
                child_resp.raise_for_status()
                child_data = child_resp.json()

                for item in child_data.get("results", []):
                    parsed = _parse_confluence_item(item, child_data, site_url)
                    if parsed and parsed["id"] not in seen_ids:
                        seen_ids.add(parsed["id"])
                        results.append(parsed)

        # max_results로 제한
        return results[:max_results]

    except Exception:
        logger.exception("Confluence 검색 실패 (cloud_id=%s, query=%s)", cloud_id, query)
        return []


def _parse_confluence_item(item: dict, data: dict, site_url: str | None) -> dict | None:
    """Confluence 검색 결과 아이템을 파싱한다."""
    content = item.get("content", item)
    page_id = str(content.get("id", ""))
    title = content.get("title", "") or item.get("title", "")
    space_name = content.get("space", {}).get("name", "") if "space" in content else ""
    excerpt = item.get("excerpt", "")

    clean_excerpt = _truncate(_strip_html(excerpt)) if excerpt else ""
    content_summary = clean_excerpt

    modified = item.get("lastModified", "") or content.get("version", {}).get("when", "")

    base_url = site_url or data.get("_links", {}).get("base", "")
    web_path = item.get("url", "") or content.get("_links", {}).get("webui", "")
    if base_url and web_path:
        # Confluence 웹 URL은 /wiki/ 접두사가 필요
        # base_url에 /wiki가 없고 web_path에도 /wiki/가 없으면 추가
        if "/wiki" not in base_url and not web_path.startswith("/wiki/"):
            web_path = "/wiki" + web_path
        link = f"{base_url}{web_path}"
    else:
        link = ""

    return {
        "id": page_id,
        "title": title,
        "space_name": space_name,
        "excerpt": clean_excerpt,
        "content_summary": content_summary,
        "modified": modified,
        "link": link,
    }
