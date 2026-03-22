import asyncio
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.auth.crypto import decrypt_token, encrypt_token
from app.config import settings

# 만료 5분 전부터 갱신 시도
_EXPIRY_BUFFER = timedelta(minutes=5)


async def get_valid_access_token(user: User, db: AsyncSession) -> str:
    expiry = user.token_expiry
    now = datetime.now(timezone.utc)

    if expiry and (expiry - now) > _EXPIRY_BUFFER:
        return decrypt_token(user.encrypted_access_token)

    # 만료 임박 또는 만료됨 → refresh
    access_token = decrypt_token(user.encrypted_access_token)
    refresh_token = decrypt_token(user.encrypted_refresh_token) if user.encrypted_refresh_token else None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )

    def _refresh():
        creds.refresh(Request())

    await asyncio.to_thread(_refresh)

    user.encrypted_access_token = encrypt_token(creds.token)
    user.token_expiry = creds.expiry
    await db.commit()

    return creds.token
