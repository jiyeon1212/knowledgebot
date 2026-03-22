import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.oauth_state import OAuthState


async def test_callback_invalid_state_returns_400_html(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/auth/google/callback?code=abc&state=invalid_state")
    assert resp.status_code == 400
    assert "text/html" in resp.headers["content-type"]
    assert "오류" in resp.text


async def test_callback_valid_state_returns_success_html_and_sends_dm(db_session):
    oauth_state = OAuthState(
        state="valid_state_token",
        slack_user_id="U123",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(oauth_state)
    await db_session.commit()

    mock_slack = AsyncMock()
    with (
        patch("app.auth.routes.asyncio.to_thread", AsyncMock(return_value={
            "access_token": "acc", "refresh_token": "ref", "expiry": None
        })),
        patch("app.auth.routes.AsyncWebClient", return_value=mock_slack),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/auth/google/callback?code=authcode&state=valid_state_token")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "연결 완료" in resp.text
    mock_slack.chat_postMessage.assert_called_once_with(
        channel="U123",
        text="✅ Google 계정이 연결됐습니다! 이제 질문을 입력해보세요.",
    )


async def test_callback_slack_dm_failure_does_not_break_response(db_session):
    """Slack DM 발송 실패해도 HTML 응답은 정상 반환되어야 한다."""
    oauth_state = OAuthState(
        state="valid_state_token2",
        slack_user_id="U456",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(oauth_state)
    await db_session.commit()

    mock_slack = AsyncMock()
    mock_slack.chat_postMessage.side_effect = Exception("Slack API 오류")
    with (
        patch("app.auth.routes.asyncio.to_thread", AsyncMock(return_value={
            "access_token": "acc", "refresh_token": "ref", "expiry": None
        })),
        patch("app.auth.routes.AsyncWebClient", return_value=mock_slack),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/auth/google/callback?code=authcode&state=valid_state_token2")

    assert resp.status_code == 200  # Slack 실패와 무관하게 성공 페이지
