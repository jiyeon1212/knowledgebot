import secrets
from urllib.parse import urlencode

import httpx

from app.config import settings

ATLASSIAN_SCOPES = [
    "read:confluence-content.all",
    "search:confluence",
    "read:jira-work",
    "offline_access",
]

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"


def build_atlassian_auth_url() -> tuple[str, str]:
    """Atlassian OAuth 인증 URL과 state를 생성한다."""
    state = secrets.token_urlsafe(32)
    params = {
        "audience": "api.atlassian.com",
        "client_id": settings.atlassian_client_id,
        "scope": " ".join(ATLASSIAN_SCOPES),
        "redirect_uri": settings.atlassian_redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    url = f"{ATLASSIAN_AUTH_URL}?{urlencode(params)}"
    return url, state


async def exchange_atlassian_code(code: str) -> dict:
    """Authorization code를 access/refresh token으로 교환한다."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": settings.atlassian_client_id,
                "client_secret": settings.atlassian_client_secret,
                "code": code,
                "redirect_uri": settings.atlassian_redirect_uri,
            },
        )
        response.raise_for_status()
        data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in"),
    }


async def get_atlassian_cloud_id(access_token: str) -> str:
    """accessible-resources API로 cloud_id를 조회한다."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            ATLASSIAN_RESOURCES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        resources = response.json()
    return resources[0]["id"]
