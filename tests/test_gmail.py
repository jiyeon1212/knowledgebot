import pytest
from unittest.mock import MagicMock, patch
from app.google.gmail import search_gmail


async def test_search_gmail_returns_snippets():
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }
    mock_service.users().messages().get().execute.return_value = {
        "snippet": "회의 일정 관련 메일 내용",
        "payload": {"headers": [{"name": "Subject", "value": "회의 안내"}]}
    }

    with patch("app.google.gmail.build_gmail_service", return_value=mock_service):
        results = await search_gmail(access_token="fake_token", query="회의")

    assert len(results) > 0
    assert "snippet" in results[0]


async def test_search_gmail_empty_result():
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {}

    with patch("app.google.gmail.build_gmail_service", return_value=mock_service):
        results = await search_gmail(access_token="fake_token", query="없는내용")

    assert results == []
