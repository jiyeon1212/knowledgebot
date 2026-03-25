import re

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from app.config import settings
from app.slack.handlers import handle_dm
from app.slack.modal import register_modal_handlers

slack_app = AsyncApp(token=settings.slack_bot_token)
register_modal_handlers(slack_app)


@slack_app.action("google_oauth_login")
async def handle_oauth_button(ack):
    await ack()

@slack_app.action("atlassian_oauth_login")
async def handle_atlassian_oauth_button(ack):
    await ack()

@slack_app.action(re.compile(r".*"))
async def handle_any_action(ack):
    """URL 버튼 등 명시적 핸들러가 없는 action을 조용히 ack 처리."""
    await ack()



@slack_app.event("message")
async def on_message(event, say):
    print(f"[DEBUG] message event received: {event}", flush=True)
    # 봇 자신의 메시지는 무시 (무한루프 방지)
    if event.get("bot_id") or event.get("subtype"):
        print(f"[DEBUG] skipping bot/subtype message", flush=True)
        return
    if event.get("channel_type") == "im":
        print(f"[DEBUG] handling DM from {event.get('user')}: {event.get('text')}", flush=True)
        await handle_dm(
            user_id=event["user"],
            text=event.get("text", ""),
            say=say,
        )


async def start_slack_bot():
    handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    await handler.start_async()
