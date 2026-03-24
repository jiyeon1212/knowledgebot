import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt_token, encrypt_token
from app.config import settings
from app.models.atlassian_user import AtlassianUser

logger = logging.getLogger(__name__)

ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

# 만료 5분 전부터 갱신 시도
_EXPIRY_BUFFER = timedelta(minutes=5)


class AtlassianReauthRequired(Exception):
    """Atlassian 토큰 갱신 실패 시 재인증이 필요함을 나타내는 예외."""

    def __init__(self) -> None:
        super().__init__("Atlassian 토큰이 만료되었습니다. 다시 인증해 주세요.")


async def get_valid_atlassian_token(
    user: AtlassianUser, db: AsyncSession
) -> tuple[str, str]:
    """유효한 (access_token, cloud_id) 튜플을 반환한다.

    토큰 만료가 5분 이내이면 refresh_token으로 자동 갱신한다.
    갱신 실패 시 AtlassianReauthRequired 예외를 발생시킨다.
    """
    now = datetime.now(timezone.utc)

    if user.token_expiry and (user.token_expiry - now) > _EXPIRY_BUFFER:
        access_token = decrypt_token(user.encrypted_access_token)
        return access_token, user.cloud_id

    # 만료 임박 또는 만료됨 → refresh
    refresh_token = (
        decrypt_token(user.encrypted_refresh_token)
        if user.encrypted_refresh_token
        else None
    )
    if not refresh_token:
        raise AtlassianReauthRequired()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": settings.atlassian_client_id,
                "client_secret": settings.atlassian_client_secret,
                "refresh_token": refresh_token,
            },
        )

    if resp.status_code != 200:
        logger.error("Atlassian 토큰 갱신 실패: %s %s", resp.status_code, resp.text)
        raise AtlassianReauthRequired()

    data = resp.json()
    new_access_token: str = data["access_token"]
    new_refresh_token: str | None = data.get("refresh_token")
    expires_in: int = data.get("expires_in", 3600)

    user.encrypted_access_token = encrypt_token(new_access_token)
    if new_refresh_token:
        user.encrypted_refresh_token = encrypt_token(new_refresh_token)
    user.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await db.commit()

    return new_access_token, user.cloud_id
