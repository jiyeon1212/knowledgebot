import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.slack.handlers import handle_dm, _distribute_results


# ---------------------------------------------------------------------------
# _distribute_results unit tests
# ---------------------------------------------------------------------------


class TestDistributeResults:
    def test_both_connected(self):
        processed = [["gmail"], ["drive"], ["confluence"], ["jira"]]
        g, d, c, j = _distribute_results(processed, google_connected=True, atlassian_connected=True)
        assert g == ["gmail"]
        assert d == ["drive"]
        assert c == ["confluence"]
        assert j == ["jira"]

    def test_google_only(self):
        processed = [["gmail"], ["drive"]]
        g, d, c, j = _distribute_results(processed, google_connected=True, atlassian_connected=False)
        assert g == ["gmail"]
        assert d == ["drive"]
        assert c == []
        assert j == []

    def test_atlassian_only(self):
        processed = [["confluence"], ["jira"]]
        g, d, c, j = _distribute_results(processed, google_connected=False, atlassian_connected=True)
        assert g == []
        assert d == []
        assert c == ["confluence"]
        assert j == ["jira"]

    def test_neither_connected(self):
        processed = []
        g, d, c, j = _distribute_results(processed, google_connected=False, atlassian_connected=False)
        assert g == []
        assert d == []
        assert c == []
        assert j == []


# ---------------------------------------------------------------------------
# handle_dm integration tests
# ---------------------------------------------------------------------------


def _mock_db_with_users(google_user=None, atlassian_user=None):
    """Create a mock DB session that returns the given users for sequential execute() calls."""
    mock_db = AsyncMock()
    google_result = MagicMock()
    google_result.scalar_one_or_none = MagicMock(return_value=google_user)
    atlassian_result = MagicMock()
    atlassian_result.scalar_one_or_none = MagicMock(return_value=atlassian_user)
    mock_db.execute = AsyncMock(side_effect=[google_result, atlassian_result])
    return mock_db


async def test_chat_intent_returns_ai_response():
    """chat 의도 시 generate_chat_response로 직접 답변한다."""
    mock_say = AsyncMock()

    with (
        patch("app.slack.handlers.classify_intent", AsyncMock(return_value={
            "intent": "chat", "search_keyword": None, "max_results": None,
        })),
        patch("app.slack.handlers.generate_chat_response", AsyncMock(return_value="안녕하세요!")),
    ):
        await handle_dm(user_id="U_CHAT", text="안녕", say=mock_say)

    mock_say.assert_called_once_with("안녕하세요!")


async def test_no_accounts_shows_both_login_buttons():
    """두 계정 모두 미연결 시 Google + Atlassian 로그인 버튼을 모두 표시한다."""
    mock_say = AsyncMock()
    mock_db = _mock_db_with_users(google_user=None, atlassian_user=None)

    with (
        patch("app.slack.handlers.classify_intent", AsyncMock(return_value={
            "intent": "search", "search_keyword": "회의록", "max_results": None,
        })),
        patch("app.slack.handlers.AsyncSessionLocal") as mock_session_cls,
        patch("app.slack.handlers.build_auth_url", return_value=("https://google.com/auth", "g_state")),
        patch("app.slack.handlers.build_atlassian_auth_url", return_value=("https://atlassian.com/auth", "a_state")),
        patch("app.slack.handlers.OAuthState"),
    ):
        mock_session_cls.return_value.__aenter__.return_value = mock_db
        await handle_dm(user_id="U_NEW", text="회의록 찾아줘", say=mock_say)

    call_kwargs = mock_say.call_args[1]
    assert "blocks" in call_kwargs
    blocks = call_kwargs["blocks"]
    # Should have actions block with 2 buttons
    actions_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(actions_blocks) == 1
    elements = actions_blocks[0]["elements"]
    action_ids = [e["action_id"] for e in elements]
    assert "google_oauth_login" in action_ids
    assert "atlassian_oauth_login" in action_ids


async def test_google_only_user_searches_and_shows_atlassian_connect():
    """Google만 연결된 사용자: Gmail+Drive 검색 후 Atlassian 연결 안내를 포함한다."""
    mock_say = AsyncMock()
    mock_google_user = MagicMock()
    mock_db = _mock_db_with_users(google_user=mock_google_user, atlassian_user=None)

    mock_blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "요약"}}]

    with (
        patch("app.slack.handlers.classify_intent", AsyncMock(return_value={
            "intent": "search", "search_keyword": "프로젝트", "max_results": 10,
        })),
        patch("app.slack.handlers.AsyncSessionLocal") as mock_session_cls,
        patch("app.slack.handlers.get_valid_access_token", AsyncMock(return_value="google_token")),
        patch("app.slack.handlers.search_gmail", AsyncMock(return_value=[{"subject": "test"}])),
        patch("app.slack.handlers.search_drive", AsyncMock(return_value=[])),
        patch("app.slack.handlers.summarize_results", AsyncMock(return_value="요약 텍스트")),
        patch("app.slack.handlers.format_search_response", return_value=mock_blocks),
        patch("app.slack.handlers.build_atlassian_auth_url", return_value=("https://atl.com/auth", "state")),
    ):
        mock_session_cls.return_value.__aenter__.return_value = mock_db
        await handle_dm(user_id="U_GOOGLE", text="프로젝트 검색", say=mock_say)

    mock_say.assert_called_once()
    call_kwargs = mock_say.call_args[1]
    assert "blocks" in call_kwargs
    assert "text" in call_kwargs


async def test_error_in_flow_sends_error_message():
    """예외 발생 시 오류 메시지를 전송한다."""
    mock_say = AsyncMock()

    with patch("app.slack.handlers.classify_intent", AsyncMock(side_effect=Exception("AI 오류"))):
        await handle_dm(user_id="U_ERR", text="질문", say=mock_say)

    assert mock_say.called
    error_msg = mock_say.call_args[0][0]
    assert "오류" in error_msg
