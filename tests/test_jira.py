import pytest
import httpx

from app.atlassian.jira import search_jira, _extract_base_url


# --- helper unit tests ---


class TestExtractBaseUrl:
    def test_extracts_base(self):
        url = "https://mysite.atlassian.net/rest/api/3/issue/10001"
        assert _extract_base_url(url) == "https://mysite.atlassian.net"

    def test_with_port(self):
        url = "https://localhost:8080/rest/api/3/issue/1"
        assert _extract_base_url(url) == "https://localhost:8080"

    def test_empty_string(self):
        assert _extract_base_url("") == "://"


# --- search_jira tests ---

_FAKE_RESPONSE = {
    "issues": [
        {
            "key": "PROJ-123",
            "self": "https://mysite.atlassian.net/rest/api/3/issue/10001",
            "fields": {
                "summary": "Fix login bug",
                "status": {"name": "In Progress"},
                "assignee": {"displayName": "홍길동"},
                "priority": {"name": "High"},
            },
        }
    ],
}


@pytest.mark.asyncio
async def test_search_jira_success(monkeypatch):
    """정상 응답 시 올바른 딕셔너리 리스트를 반환한다."""

    async def _mock_get(self, url, *, params=None, headers=None):
        return httpx.Response(200, json=_FAKE_RESPONSE, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_jira("tok", "cloud-1", "login")

    assert len(results) == 1
    r = results[0]
    assert r["key"] == "PROJ-123"
    assert r["title"] == "Fix login bug"
    assert r["status"] == "In Progress"
    assert r["assignee"] == "홍길동"
    assert r["priority"] == "High"
    assert r["link"] == "https://mysite.atlassian.net/browse/PROJ-123"


@pytest.mark.asyncio
async def test_search_jira_null_assignee(monkeypatch):
    """담당자가 null이면 '미지정'으로 반환한다."""

    response_data = {
        "issues": [
            {
                "key": "PROJ-456",
                "self": "https://mysite.atlassian.net/rest/api/3/issue/10002",
                "fields": {
                    "summary": "Unassigned task",
                    "status": {"name": "Open"},
                    "assignee": None,
                    "priority": {"name": "Medium"},
                },
            }
        ],
    }

    async def _mock_get(self, url, *, params=None, headers=None):
        return httpx.Response(200, json=response_data, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_jira("tok", "cloud-1", "task")
    assert results[0]["assignee"] == "미지정"


@pytest.mark.asyncio
async def test_search_jira_empty_results(monkeypatch):
    """검색 결과가 없으면 빈 리스트를 반환한다."""

    async def _mock_get(self, url, *, params=None, headers=None):
        return httpx.Response(200, json={"issues": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_jira("tok", "cloud-1", "nothing")
    assert results == []


@pytest.mark.asyncio
async def test_search_jira_api_error_returns_empty(monkeypatch):
    """API 오류 시 빈 리스트를 반환한다 (Requirements 9.2)."""

    async def _mock_get(self, url, *, params=None, headers=None):
        return httpx.Response(500, text="Internal Server Error", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_jira("tok", "cloud-1", "fail")
    assert results == []


@pytest.mark.asyncio
async def test_search_jira_network_error_returns_empty(monkeypatch):
    """네트워크 오류 시 빈 리스트를 반환한다."""

    async def _mock_get(self, url, *, params=None, headers=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    results = await search_jira("tok", "cloud-1", "fail")
    assert results == []
