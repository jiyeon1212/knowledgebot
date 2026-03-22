import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.slack.handlers import handle_dm


async def test_new_user_gets_oauth_button():
    mock_say = AsyncMock()
    mock_db = AsyncMock()
    # Python 3.14: AsyncMock child attrs are also AsyncMock, so scalar_one_or_none()
    # returns a coroutine. Use MagicMock explicitly to get a sync return value.
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)  # 신규 사용자

    with (
        patch("app.slack.handlers.AsyncSessionLocal") as mock_session_cls,
        patch("app.slack.handlers.build_auth_url", return_value=("https://google.com/auth", "state123")),
        patch("app.slack.handlers.OAuthState"),
    ):
        mock_session_cls.return_value.__aenter__.return_value = mock_db
        await handle_dm(user_id="U_NEW", text="안녕", say=mock_say)

    call_kwargs = mock_say.call_args[1]
    assert "blocks" in call_kwargs
    block_types = [b.get("type") for b in call_kwargs["blocks"]]
    assert "actions" in block_types


async def test_existing_user_gets_summary():
    mock_user = MagicMock()
    mock_say = AsyncMock()
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=mock_user)

    with (
        patch("app.slack.handlers.AsyncSessionLocal") as mock_session_cls,
        patch("app.slack.handlers.get_valid_access_token", AsyncMock(return_value="real_token")),
        patch("app.slack.handlers.search_gmail", AsyncMock(return_value=[])),
        patch("app.slack.handlers.search_drive", AsyncMock(return_value=[])),
        patch("app.slack.handlers.summarize_results", AsyncMock(return_value="답변입니다.")),
    ):
        mock_session_cls.return_value.__aenter__.return_value = mock_db
        await handle_dm(user_id="U_OLD", text="회의 일정", say=mock_say)

    mock_say.assert_called_once_with("답변입니다.")


async def test_error_in_flow_sends_error_message():
    mock_say = AsyncMock()
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("DB 오류")

    with patch("app.slack.handlers.AsyncSessionLocal") as mock_session_cls:
        mock_session_cls.return_value.__aenter__.return_value = mock_db
        await handle_dm(user_id="U_ERR", text="질문", say=mock_say)

    assert mock_say.called
    error_msg = mock_say.call_args[0][0]
    assert "오류" in error_msg or "실패" in error_msg
