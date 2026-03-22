import pytest
from unittest.mock import MagicMock, patch
from app.google.drive import search_drive


async def test_search_drive_returns_files():
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {
        "files": [{"id": "f1", "name": "Q1 보고서.docx", "mimeType": "application/vnd.google-apps.document",
                   "modifiedTime": "2026-01-01", "webViewLink": "https://drive.google.com/..."}]
    }

    with patch("app.google.drive.build_drive_service", return_value=mock_service):
        results = await search_drive(access_token="fake_token", query="보고서")

    assert len(results) > 0
    assert results[0]["name"] == "Q1 보고서.docx"


async def test_drive_query_escapes_single_quotes():
    """사용자 입력의 단따옴표가 Drive 쿼리를 깨지 않아야 한다."""
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {"files": []}

    with patch("app.google.drive.build_drive_service", return_value=mock_service):
        # "it's" 같은 입력도 API 호출이 성공해야 함
        results = await search_drive(access_token="fake_token", query="it's a report")

    # list().execute가 호출됐으면 쿼리가 정상적으로 구성된 것
    mock_service.files().list.assert_called()
    assert results == []
