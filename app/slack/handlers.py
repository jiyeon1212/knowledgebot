import logging
import traceback
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.oauth_state import OAuthState
from app.auth.google_oauth import build_auth_url
from app.google.gmail import search_gmail
from app.google.drive import search_drive
from app.google.token_refresh import get_valid_access_token
from app.ai.summarizer import summarize_results

_STATE_TTL_MINUTES = 10


async def handle_dm(user_id: str, text: str, say) -> None:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.slack_user_id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                auth_url, state = build_auth_url()
                oauth_state = OAuthState(
                    state=state,
                    slack_user_id=user_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES),
                )
                db.add(oauth_state)
                await db.commit()

                await say(
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "안녕하세요! 먼저 Google 계정을 연결해주세요."},
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Google 로그인"},
                                    "url": auth_url,
                                    "action_id": "google_oauth_login",
                                }
                            ],
                        },
                    ],
                    text="Google 계정 연결이 필요합니다.",
                )
                return

            access_token = await get_valid_access_token(user=user, db=db)

        # Gmail은 키워드 검색 — 자연어 질문이면 최근 메일 가져오기
        gmail_query = text
        if any(kw in text for kw in ["최근", "요약", "정리", "알려줘", "있어?", "있으면"]):
            gmail_query = "newer_than:7d"
        gmail_results = await search_gmail(access_token=access_token, query=gmail_query)
        print(f"[DEBUG] gmail_query: '{gmail_query}', gmail_results({len(gmail_results)}): {gmail_results[:2]}", flush=True)
        drive_results = await search_drive(access_token=access_token, query=text)
        print(f"[DEBUG] drive_results({len(drive_results)}): {drive_results}", flush=True)
        summary = await summarize_results(
            question=text,
            gmail_results=gmail_results,
            drive_results=drive_results,
        )
        print(f"[DEBUG] summary: {repr(summary)}", flush=True)
        await say(summary)

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        print(f"[ERROR] handle_dm failed for user {user_id}: {type(e).__name__}: {e}", flush=True)
        await say(f"오류 발생: {type(e).__name__}: {e}")
