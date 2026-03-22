from app.models.user import User
from app.models.oauth_state import OAuthState
from datetime import datetime, timezone


def test_user_model_fields():
    u = User(
        slack_user_id="U123",
        encrypted_access_token="enc_token",
        encrypted_refresh_token="enc_refresh",
    )
    assert u.slack_user_id == "U123"


def test_oauth_state_model_fields():
    s = OAuthState(
        state="random_token",
        slack_user_id="U123",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert s.state == "random_token"
    assert s.slack_user_id == "U123"
