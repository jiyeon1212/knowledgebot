import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.ai.summarizer import classify_intent, extract_search_query


def _mock_gemini_response(text: str):
    """Helper to create a mock Gemini client that returns the given text."""
    mock_response = MagicMock()
    mock_response.text = text
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio
    return mock_client


class TestClassifyIntent:
    async def test_search_intent(self):
        response_json = json.dumps(
            {"intent": "search", "search_keyword": "지난주 회의록", "max_results": None}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("지난주 회의록 찾아줘")

        assert result["intent"] == "search"
        assert result["search_keyword"] == "지난주 회의록"
        assert result["max_results"] is None

    async def test_chat_intent(self):
        response_json = json.dumps(
            {"intent": "chat", "search_keyword": None, "max_results": None}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("안녕하세요")

        assert result["intent"] == "chat"
        assert result["search_keyword"] is None
        assert result["max_results"] is None

    async def test_search_with_max_results(self):
        response_json = json.dumps(
            {"intent": "search", "search_keyword": "프로젝트 제안서", "max_results": 20}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("프로젝트 제안서 20개 보여줘")

        assert result["intent"] == "search"
        assert result["search_keyword"] == "프로젝트 제안서"
        assert result["max_results"] == 20

    async def test_json_parse_error_fallback(self):
        mock_client = _mock_gemini_response("이것은 유효하지 않은 JSON입니다")

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("테스트 질문")

        assert result["intent"] == "search"
        assert result["search_keyword"] == "테스트 질문"
        assert result["max_results"] is None

    async def test_markdown_code_fence_stripped(self):
        response_text = '```json\n{"intent": "chat", "search_keyword": null, "max_results": null}\n```'
        mock_client = _mock_gemini_response(response_text)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("너의 이름은 뭐야?")

        assert result["intent"] == "chat"
        assert result["search_keyword"] is None

    async def test_invalid_intent_defaults_to_search(self):
        response_json = json.dumps(
            {"intent": "unknown", "search_keyword": "테스트", "max_results": None}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("테스트")

        assert result["intent"] == "search"

    async def test_null_string_keyword_treated_as_none(self):
        response_json = json.dumps(
            {"intent": "chat", "search_keyword": "null", "max_results": None}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await classify_intent("안녕")

        assert result["search_keyword"] is None


class TestExtractSearchQueryBackwardCompat:
    async def test_search_intent_returns_keyword(self):
        response_json = json.dumps(
            {"intent": "search", "search_keyword": "회의록", "max_results": None}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await extract_search_query("지난주 회의록 찾아줘")

        assert result == "회의록"

    async def test_chat_intent_returns_original_text(self):
        response_json = json.dumps(
            {"intent": "chat", "search_keyword": None, "max_results": None}
        )
        mock_client = _mock_gemini_response(response_json)

        with patch("app.ai.summarizer._get_client", return_value=mock_client):
            result = await extract_search_query("안녕하세요")

        assert result == "안녕하세요"
