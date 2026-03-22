import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from app.google.token_refresh import get_valid_access_token
from app.models.user import User


def make_user(expiry_offset_minutes: int):
    user = MagicMock(spec=User)
    user.encrypted_access_token = "enc_access"
    user.encrypted_refresh_token = "enc_refresh"
    user.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=expiry_offset_minutes)
    return user


async def test_valid_token_returned_without_refresh():
    user = make_user(expiry_offset_minutes=30)  # 아직 30분 남음
    mock_db = AsyncMock()

    with patch("app.google.token_refresh.decrypt_token", return_value="real_access"):
        token = await get_valid_access_token(user=user, db=mock_db)

    assert token == "real_access"
    mock_db.commit.assert_not_called()  # 갱신 불필요


async def test_expired_token_triggers_refresh():
    user = make_user(expiry_offset_minutes=-5)  # 5분 전에 만료
    mock_db = AsyncMock()

    mock_creds = MagicMock()
    mock_creds.token = "new_access"
    mock_creds.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    with (
        patch("app.google.token_refresh.decrypt_token", side_effect=["old_access", "ref_token"]),
        patch("app.google.token_refresh.Credentials", return_value=mock_creds),
        patch("app.google.token_refresh.Request"),
        patch("app.google.token_refresh.encrypt_token", return_value="new_enc"),
    ):
        mock_creds.expired = True
        mock_creds.refresh_token = "ref_token"
        mock_creds.refresh = MagicMock()
        token = await get_valid_access_token(user=user, db=mock_db)

    assert token == "new_access"
