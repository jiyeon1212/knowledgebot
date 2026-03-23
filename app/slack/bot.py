from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from app.config import settings
from app.slack.handlers import handle_dm

slack_app = AsyncApp(token=settings.slack_bot_token)


@slack_app.action("google_oauth_login")
async def handle_oauth_button(ack):
    await ack()


@slack_app.event("message")
async def on_message(event, say):
    # 봇 자신의 메시지는 무시 (무한루프 방지)
    if event.get("bot_id") or event.get("subtype"):
        return
    if event.get("channel_type") == "im":
        await handle_dm(
            user_id=event["user"],
            text=event.get("text", ""),
            say=say,
        )


async def start_slack_bot():
    handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    await handler.start_async()
