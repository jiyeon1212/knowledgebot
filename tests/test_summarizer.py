import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.ai.summarizer import summarize_results


async def test_summarize_returns_string():
    mock_response = MagicMock()
    mock_response.text = "회의 일정은 3월 25일입니다."
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        result = await summarize_results(
            question="다음 회의는 언제야?",
            gmail_results=[{"subject": "회의 안내", "snippet": "3월 25일 오후 2시", "from": "boss@co.kr"}],
            drive_results=[],
        )

    assert isinstance(result, str)
    assert len(result) > 0


async def test_summarize_no_results():
    mock_response = MagicMock()
    mock_response.text = "관련 정보를 찾지 못했습니다."
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        result = await summarize_results(question="존재하지않는내용", gmail_results=[], drive_results=[])

    assert isinstance(result, str)
