import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from sqlalchemy import delete
from app.auth.routes import router as auth_router
from app.database import AsyncSessionLocal
from app.models.oauth_state import OAuthState

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 만료된 OAuth state 레코드 정리
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OAuthState).where(OAuthState.expires_at < datetime.now(timezone.utc)))
        await db.commit()
    logger.info("Expired OAuth states cleaned up")
    # Slack bot을 백그라운드에서 시작
    try:
        from app.slack.bot import start_slack_bot
        asyncio.create_task(start_slack_bot())
    except Exception:
        logger.exception("Failed to start Slack bot")
    yield


app = FastAPI(title="knowledge-bot", lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/oauth")
async def debug_oauth():
    """임시 디버그 엔드포인트 — 배포 후 삭제할 것."""
    from app.config import settings
    return {
        "google_redirect_uri": settings.google_redirect_uri,
        "google_client_id": settings.google_client_id[:20] + "...",
        "atlassian_redirect_uri": settings.atlassian_redirect_uri,
        "app_base_url": settings.app_base_url,
    }
