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

from app.ai.summarizer import summarize_entity_results


async def test_summarize_entity_results_returns_summary():
    """검색 결과가 있을 때 엔티티 중심 요약문을 반환한다."""
    mock_response = MagicMock()
    mock_response.text = "신한은행 관련 주요 이벤트: 계약 갱신 논의. 관련 담당자: 김철수. 미결 사항: 2건"
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        result = await summarize_entity_results(
            entity_name="신한은행",
            entity_type="고객사",
            gmail_results=[{"subject": "신한은행 계약 갱신", "from": "kim@co.kr", "snippet": "계약 갱신 논의"}],
            drive_results=[{"name": "신한은행_제안서.pdf", "modified": "2025-03-01"}],
            confluence_results=[{"title": "신한은행 미팅 노트", "content_summary": "3월 미팅 내용", "modified": "2025-03-10"}],
            jira_results=[{"key": "PROJ-101", "title": "신한은행 요구사항 반영", "status": "진행중", "assignee": "김철수", "priority": "High"}],
        )

    assert isinstance(result, str)
    assert len(result) > 0


async def test_summarize_entity_results_empty_results():
    """검색 결과가 모두 비어있을 때도 정상 동작한다."""
    mock_response = MagicMock()
    mock_response.text = "관련 정보를 찾지 못했습니다."
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        result = await summarize_entity_results(
            entity_name="테스트회사",
            entity_type="고객사",
            gmail_results=[],
            drive_results=[],
            confluence_results=[],
            jira_results=[],
        )

    assert isinstance(result, str)


async def test_summarize_entity_results_partial_results():
    """일부 플랫폼만 결과가 있을 때도 정상 동작한다."""
    mock_response = MagicMock()
    mock_response.text = "Jira 미결 이슈 1건 확인됨."
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        result = await summarize_entity_results(
            entity_name="김철수",
            entity_type="담당자",
            gmail_results=[],
            drive_results=[],
            confluence_results=[],
            jira_results=[{"key": "TASK-42", "title": "버그 수정", "status": "진행중", "assignee": "김철수", "priority": "Medium"}],
        )

    assert isinstance(result, str)
    assert len(result) > 0


from app.ai.summarizer import filter_irrelevant_results


async def test_filter_irrelevant_results_returns_relevant_only():
    """AI가 관련 있는 인덱스만 반환하면 해당 결과만 남긴다."""
    mock_response = MagicMock()
    mock_response.text = '{"relevant_indices": [0, 2]}'
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    results = [
        {"subject": "미래에셋 계약", "from": "a@co.kr", "snippet": "계약 논의"},
        {"subject": "주간 보고", "from": "b@co.kr", "snippet": "미래에셋 서명란"},
        {"subject": "미래에셋 제안서", "from": "c@co.kr", "snippet": "제안서 검토"},
        {"subject": "점심 메뉴", "from": "d@co.kr", "snippet": "미래에셋빌딩 근처"},
    ]

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        filtered = await filter_irrelevant_results("미래에셋", results, "gmail")

    assert len(filtered) == 2
    assert filtered[0]["subject"] == "미래에셋 계약"
    assert filtered[1]["subject"] == "미래에셋 제안서"


async def test_filter_irrelevant_results_skips_small_lists():
    """결과가 3개 이하면 필터링 없이 그대로 반환한다."""
    results = [
        {"subject": "미래에셋 계약", "from": "a@co.kr", "snippet": "계약"},
        {"subject": "미래에셋 보고", "from": "b@co.kr", "snippet": "보고"},
    ]

    # _get_client가 호출되지 않아야 함
    filtered = await filter_irrelevant_results("미래에셋", results, "gmail")
    assert len(filtered) == 2


async def test_filter_irrelevant_results_empty_list():
    """빈 리스트는 그대로 반환한다."""
    filtered = await filter_irrelevant_results("미래에셋", [], "gmail")
    assert filtered == []


async def test_filter_irrelevant_results_api_error_returns_original():
    """AI 호출 실패 시 원본 결과를 그대로 반환한다."""
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(side_effect=Exception("API error"))
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    results = [
        {"subject": "A", "from": "a@co.kr", "snippet": "x"},
        {"subject": "B", "from": "b@co.kr", "snippet": "y"},
        {"subject": "C", "from": "c@co.kr", "snippet": "z"},
        {"subject": "D", "from": "d@co.kr", "snippet": "w"},
    ]

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        filtered = await filter_irrelevant_results("미래에셋", results, "gmail")

    assert len(filtered) == 4  # 원본 그대로


async def test_filter_irrelevant_results_zero_relevant_returns_empty():
    """AI가 관련 결과 0건을 반환하면 빈 리스트를 반환한다."""
    mock_response = MagicMock()
    mock_response.text = '{"relevant_indices": []}'
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    results = [
        {"subject": "A", "from": "a@co.kr", "snippet": "x"},
        {"subject": "B", "from": "b@co.kr", "snippet": "y"},
        {"subject": "C", "from": "c@co.kr", "snippet": "z"},
        {"subject": "D", "from": "d@co.kr", "snippet": "w"},
    ]

    with patch("app.ai.summarizer._get_client", return_value=mock_client):
        filtered = await filter_irrelevant_results("미래에셋", results, "gmail")

    assert len(filtered) == 0  # 관련 없으면 빈 리스트


# ---------------------------------------------------------------------------
# Claude 통합 테스트
# ---------------------------------------------------------------------------
from app.ai.summarizer import (
    generate_chat_response,
    _use_claude,
)


async def test_summarize_results_uses_claude_when_configured():
    """ANTHROPIC_API_KEY가 설정되면 Claude를 사용한다."""
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Claude 요약 결과")]
    mock_claude = AsyncMock()
    mock_claude.messages.create = AsyncMock(return_value=mock_msg)

    with (
        patch("app.ai.summarizer._use_claude", return_value=True),
        patch("app.ai.summarizer._get_claude_client", return_value=mock_claude),
    ):
        result = await summarize_results(
            question="테스트 질문",
            gmail_results=[{"subject": "테스트", "from": "a@co.kr", "snippet": "내용"}],
            drive_results=[],
            user_id="U_TEST",
        )

    assert result == "Claude 요약 결과"
    mock_claude.messages.create.assert_called_once()
    call_kwargs = mock_claude.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"


async def test_summarize_results_falls_back_to_gemini():
    """ANTHROPIC_API_KEY가 없으면 Gemini fallback."""
    mock_response = MagicMock()
    mock_response.text = "Gemini 요약 결과"
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with (
        patch("app.ai.summarizer._use_claude", return_value=False),
        patch("app.ai.summarizer._get_client", return_value=mock_client),
    ):
        result = await summarize_results(
            question="테스트 질문",
            gmail_results=[],
            drive_results=[],
        )

    assert result == "Gemini 요약 결과"


async def test_generate_chat_response_uses_claude():
    """Claude가 설정되면 chat 응답도 Claude를 사용한다."""
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="안녕하세요!")]
    mock_claude = AsyncMock()
    mock_claude.messages.create = AsyncMock(return_value=mock_msg)

    with (
        patch("app.ai.summarizer._use_claude", return_value=True),
        patch("app.ai.summarizer._get_claude_client", return_value=mock_claude),
    ):
        result = await generate_chat_response("안녕", user_id="U_CHAT")

    assert result == "안녕하세요!"


async def test_generate_chat_response_gemini_fallback():
    """Claude 미설정 시 Gemini로 chat 응답."""
    mock_response = MagicMock()
    mock_response.text = "Gemini 안녕!"
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(return_value=mock_response)
    mock_aio = MagicMock()
    mock_aio.models = mock_models
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with (
        patch("app.ai.summarizer._use_claude", return_value=False),
        patch("app.ai.summarizer._get_client", return_value=mock_client),
    ):
        result = await generate_chat_response("안녕")

    assert result == "Gemini 안녕!"
