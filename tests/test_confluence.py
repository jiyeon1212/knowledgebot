import pytest
import httpx

from app.atlassian.confluence import search_confluence, _strip_html, _truncate


# --- helper unit tests ---


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        assert _strip_html("<p>a</p>  <p>b</p>") == "a b"

    def test_empty_string(self):
        assert _strip_html("") == ""


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 200) == "hello"

    def test_long_text_truncated(self):
        text = "word " * 100  # 500 chars
        result = _truncate(text, 200)
        assert len(result) <= 201  # +1 for ellipsis char
        assert result.endswith("…")

    def test_exact_boundary(self):
        text = "a" * 200
        assert _truncate(text, 200) == text


# --- search_confluence tests ---

_FAKE_RESPONSE = {
    "_links": {"base": "https://mysite.atlassian.net/wiki"},
    "results": [
        {
            "content": {
                "title": "Meeting Notes",
                "space": {"name": "Engineering"},
                "version": {"when": "2024-06-01T10:00:00.000Z"},
                "_links": {"webui": "/spaces/ENG/pages/12345/Meeting+Notes"},
            },
            "title": "Meeting Notes",
            "excerpt": "Weekly sync notes",
            "url": "/spaces/ENG/pages/12345/Meeting+Notes",
            "lastModified": "2024-06-01T10:00:00.000Z",
        }
    ],
}


@pytest.mark.asyncio
async def test_search_confluence_success(monkeypatch):
    """정상 응답 시 올바른 딕셔너리 리스트를 반환한다."""

    async def _mock_get(self, url, *, params=None, headers=None):
        resp = httpx.Response(200, json=_FAKE_RESPONSE, request=httpx.Request("GET", url))
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_confluence("tok", "cloud-1", "roadmap")

    assert len(results) == 1
    r = results[0]
    assert r["title"] == "Meeting Notes"
    assert r["space_name"] == "Engineering"
    assert r["excerpt"] == "Weekly sync notes"
    assert r["content_summary"] == "Weekly sync notes"
    assert r["modified"] == "2024-06-01T10:00:00.000Z"
    assert r["link"] == "https://mysite.atlassian.net/wiki/spaces/ENG/pages/12345/Meeting+Notes"


@pytest.mark.asyncio
async def test_search_confluence_empty_results(monkeypatch):
    """검색 결과가 없으면 빈 리스트를 반환한다."""

    async def _mock_get(self, url, *, params=None, headers=None):
        resp = httpx.Response(
            200,
            json={"_links": {"base": "https://x.atlassian.net/wiki"}, "results": []},
            request=httpx.Request("GET", url),
        )
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_confluence("tok", "cloud-1", "nothing")
    assert results == []


@pytest.mark.asyncio
async def test_search_confluence_api_error_returns_empty(monkeypatch):
    """API 오류 시 빈 리스트를 반환한다 (Requirements 9.1)."""

    async def _mock_get(self, url, *, params=None, headers=None):
        resp = httpx.Response(500, text="Internal Server Error", request=httpx.Request("GET", url))
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_confluence("tok", "cloud-1", "fail")
    assert results == []


@pytest.mark.asyncio
async def test_search_confluence_network_error_returns_empty(monkeypatch):
    """네트워크 오류 시 빈 리스트를 반환한다."""

    async def _mock_get(self, url, *, params=None, headers=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_confluence("tok", "cloud-1", "fail")
    assert results == []
