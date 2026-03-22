import secrets
from google_auth_oauthlib.flow import Flow
from app.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uris": [settings.google_redirect_uri],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def build_auth_url() -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    url, _ = flow.authorization_url(access_type="offline", state=state, prompt="consent")
    return url, state


def exchange_code_for_tokens(code: str) -> dict:
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expiry": creds.expiry,
    }
