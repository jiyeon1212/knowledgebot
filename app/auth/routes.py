import asyncio
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from slack_sdk.web.async_client import AsyncWebClient
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.oauth_state import OAuthState
from app.auth.google_oauth import exchange_code_for_tokens
from app.auth.atlassian_oauth import exchange_atlassian_code, get_atlassian_cloud_id
from app.auth.crypto import encrypt_token
from app.models.atlassian_user import AtlassianUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth")

_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>연결 완료</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center;
            align-items: center; min-height: 100vh; margin: 0; background: #f8f9fa; }}
    .card {{ text-align: center; padding: 48px; background: white; border-radius: 12px;
             box-shadow: 0 2px 16px rgba(0,0,0,.1); max-width: 400px; }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h1 {{ color: #1a1a1a; margin: 0 0 8px; font-size: 24px; }}
    p {{ color: #666; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>Google 계정 연결 완료!</h1>
    <p>Slack으로 돌아가서 질문해보세요.</p>
  </div>
</body>
</html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>오류</title></head>
<body style="font-family:sans-serif;text-align:center;padding:48px">
  <h1>⚠️ 인증 오류</h1>
  <p>유효하지 않거나 만료된 요청입니다. Slack에서 다시 시도해주세요.</p>
</body>
</html>"""

@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    # state 검증 (CSRF 방어)
    result = await db.execute(
        select(OAuthState).where(
            OAuthState.state == state,
            OAuthState.expires_at > datetime.now(timezone.utc),
        )
    )
    oauth_state = result.scalar_one_or_none()
    if not oauth_state:
        return HTMLResponse(content=_ERROR_HTML, status_code=400)

    slack_user_id = oauth_state.slack_user_id

    # 사용한 state 삭제
    await db.execute(delete(OAuthState).where(OAuthState.id == oauth_state.id))

    # 토큰 교환 (google-auth-oauthlib은 blocking HTTP → 이벤트 루프 차단 방지)
    tokens = await asyncio.to_thread(exchange_code_for_tokens, code)

    # DB upsert
    user_result = await db.execute(select(User).where(User.slack_user_id == slack_user_id))
    user = user_result.scalar_one_or_none()

    enc_access = encrypt_token(tokens["access_token"])
    enc_refresh = encrypt_token(tokens["refresh_token"]) if tokens["refresh_token"] else None

    if user:
        user.encrypted_access_token = enc_access
        user.encrypted_refresh_token = enc_refresh
        user.token_expiry = tokens["expiry"]
    else:
        user = User(
            slack_user_id=slack_user_id,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_expiry=tokens["expiry"],
        )
        db.add(user)

    await db.commit()

    # Slack DM 자동 발송 — 실패해도 OAuth 결과에 영향 없음
    try:
        slack_client = AsyncWebClient(token=settings.slack_bot_token)
        await slack_client.chat_postMessage(
            channel=slack_user_id,
            text="✅ Google 계정이 연결됐습니다! 이제 질문을 입력해보세요.",
        )
    except Exception:
        logger.exception("Failed to send Slack DM after OAuth for user %s", slack_user_id)

    # 검색 Modal 버튼 발송
    from app.slack.modal import send_search_button
    await send_search_button(slack_user_id)

    return HTMLResponse(content=_SUCCESS_HTML)

_ATLASSIAN_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>연결 완료</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center;
            align-items: center; min-height: 100vh; margin: 0; background: #f8f9fa; }}
    .card {{ text-align: center; padding: 48px; background: white; border-radius: 12px;
             box-shadow: 0 2px 16px rgba(0,0,0,.1); max-width: 400px; }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h1 {{ color: #1a1a1a; margin: 0 0 8px; font-size: 24px; }}
    p {{ color: #666; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>Atlassian 계정 연결 완료!</h1>
    <p>Slack으로 돌아가서 질문해보세요.</p>
  </div>
</body>
</html>"""


@router.get("/atlassian/callback", response_class=HTMLResponse)
async def atlassian_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    """Atlassian OAuth 콜백을 처리한다."""
    logger.info("Atlassian callback 수신: state=%s", state[:16] if state else "None")
    # 1. state 검증 (CSRF 방어) — OAuthState 테이블 재사용
    result = await db.execute(
        select(OAuthState).where(
            OAuthState.state == state,
            OAuthState.expires_at > datetime.now(timezone.utc),
        )
    )
    oauth_state = result.scalar_one_or_none()
    if not oauth_state:
        return HTMLResponse(content=_ERROR_HTML, status_code=400)

    slack_user_id = oauth_state.slack_user_id

    # 사용한 state 삭제
    await db.execute(delete(OAuthState).where(OAuthState.id == oauth_state.id))

    try:
        # 2. 토큰 교환
        tokens = await exchange_atlassian_code(code)

        # 3. cloud_id 조회
        cloud_id = await get_atlassian_cloud_id(tokens["access_token"])
    except Exception:
        logger.exception("Atlassian OAuth token exchange/cloud_id failed for user %s", slack_user_id)
        return HTMLResponse(content=_ERROR_HTML, status_code=400)

    # 4. 토큰 암호화
    enc_access = encrypt_token(tokens["access_token"])
    enc_refresh = encrypt_token(tokens["refresh_token"]) if tokens.get("refresh_token") else None

    # 5. token_expiry 계산
    token_expiry = None
    if tokens.get("expires_in"):
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])

    # 6. AtlassianUser upsert (기존 레코드 있으면 갱신)
    user_result = await db.execute(
        select(AtlassianUser).where(AtlassianUser.slack_user_id == slack_user_id)
    )
    user = user_result.scalar_one_or_none()

    if user:
        user.encrypted_access_token = enc_access
        user.encrypted_refresh_token = enc_refresh
        user.token_expiry = token_expiry
        user.cloud_id = cloud_id
    else:
        user = AtlassianUser(
            slack_user_id=slack_user_id,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_expiry=token_expiry,
            cloud_id=cloud_id,
        )
        db.add(user)

    await db.commit()

    # Slack DM 자동 발송 — 실패해도 OAuth 결과에 영향 없음
    try:
        slack_client = AsyncWebClient(token=settings.slack_bot_token)
        await slack_client.chat_postMessage(
            channel=slack_user_id,
            text="✅ Atlassian 계정이 연결됐습니다! 이제 Confluence/Jira 검색이 가능합니다.",
        )
    except Exception:
        logger.exception("Failed to send Slack DM after Atlassian OAuth for user %s", slack_user_id)

    # 검색 Modal 버튼 발송
    from app.slack.modal import send_search_button
    await send_search_button(slack_user_id)

    return HTMLResponse(content=_ATLASSIAN_SUCCESS_HTML)

