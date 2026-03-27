"""Slack Modal — 검색 폼 (카테고리/프로젝트명/기간) + 로그인 후 검색 버튼 발송."""

import logging
from datetime import datetime, timedelta, timezone

from slack_sdk.web.async_client import AsyncWebClient

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Modal 정의
# ---------------------------------------------------------------------------

SEARCH_MODAL = {
    "type": "modal",
    "callback_id": "search_modal_submit",
    "title": {"type": "plain_text", "text": "🔍 지식 검색"},
    "submit": {"type": "plain_text", "text": "검색하기"},
    "close": {"type": "plain_text", "text": "취소"},
    "blocks": [
        {
            "type": "input",
            "block_id": "category_block",
            "label": {"type": "plain_text", "text": "📂 카테고리"},
            "element": {
                "type": "static_select",
                "action_id": "category_select",
                "placeholder": {"type": "plain_text", "text": "선택하세요"},
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "📋 사업"},
                        "value": "business",
                    },
                    {
                        "text": {"type": "plain_text", "text": "💻 개발"},
                        "value": "development",
                    },
                ],
            },
        },
        {
            "type": "input",
            "block_id": "project_block",
            "label": {"type": "plain_text", "text": "🏷️ 프로젝트명"},
            "element": {
                "type": "plain_text_input",
                "action_id": "project_input",
                "placeholder": {"type": "plain_text", "text": "예: broof, 브루프"},
            },
        },
        {
            "type": "input",
            "block_id": "date_preset_block",
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "📅 기간"},
            "element": {
                "type": "static_select",
                "action_id": "date_preset_select",
                "initial_option": {
                    "text": {"type": "plain_text", "text": "전체"},
                    "value": "all",
                },
                "options": [
                    {"text": {"type": "plain_text", "text": "전체"}, "value": "all"},
                    {"text": {"type": "plain_text", "text": "최근 1주일"}, "value": "1w"},
                    {"text": {"type": "plain_text", "text": "최근 1개월"}, "value": "1m"},
                    {"text": {"type": "plain_text", "text": "최근 3개월"}, "value": "3m"},
                    {"text": {"type": "plain_text", "text": "최근 6개월"}, "value": "6m"},
                    {"text": {"type": "plain_text", "text": "최근 1년"}, "value": "1y"},
                    {"text": {"type": "plain_text", "text": "✏️ 직접 입력"}, "value": "custom"},
                ],
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# 로그인 완료 후 "검색하기" 버튼 DM 발송
# ---------------------------------------------------------------------------

SEARCH_BUTTON_BLOCKS = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "✅ *계정 연결 완료!*",
        },
    },
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "🔍 *검색하기* 버튼을 누르시면 카테고리·기간 등을 직접 지정해 더 정확한 검색을 할 수 있습니다.",
        },
    },
    {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔍 검색하기"},
                "style": "primary",
                "action_id": "open_search_modal",
            },
        ],
    },
]


async def send_search_button(slack_user_id: str) -> None:
    """로그인 완료 후 검색 버튼을 DM으로 발송한다."""
    try:
        client = AsyncWebClient(token=settings.slack_bot_token)
        await client.chat_postMessage(
            channel=slack_user_id,
            blocks=SEARCH_BUTTON_BLOCKS,
            text="계정 연결 완료! 검색하기 버튼을 눌러주세요.",
        )
    except Exception:
        logger.exception("Failed to send search button to %s", slack_user_id)


# ---------------------------------------------------------------------------
# Modal 열기 핸들러 (버튼 클릭 시)
# ---------------------------------------------------------------------------

DATE_CUSTOM_BLOCK = {
    "type": "input",
    "block_id": "date_custom_block",
    "optional": True,
    "label": {"type": "plain_text", "text": "✏️ 기간 직접 입력"},
    "element": {
        "type": "plain_text_input",
        "action_id": "date_custom_input",
        "placeholder": {"type": "plain_text", "text": "예: 2025년 하반기, 작년 Q3, 최근 2개월"},
    },
}


async def handle_date_preset_change(ack, body, client):
    """기간 드롭다운 변경 시 '직접 입력' 선택이면 텍스트 입력칸을 추가한다."""
    await ack()
    selected = body["actions"][0]["selected_option"]["value"]
    view = body["view"]

    # 현재 블록 복사
    new_blocks = [b for b in view["blocks"] if b["block_id"] != "date_custom_block"]

    if selected == "custom":
        # date_preset_block 다음 위치에 직접 입력 블록 삽입
        insert_idx = next(
            (i + 1 for i, b in enumerate(new_blocks) if b["block_id"] == "date_preset_block"),
            len(new_blocks),
        )
        new_blocks.insert(insert_idx, DATE_CUSTOM_BLOCK)

    await client.views_update(
        view_id=view["id"],
        view={
            "type": "modal",
            "callback_id": "search_modal_submit",
            "title": {"type": "plain_text", "text": "🔍 지식 검색"},
            "submit": {"type": "plain_text", "text": "검색하기"},
            "close": {"type": "plain_text", "text": "취소"},
            "blocks": new_blocks,
        },
    )


async def handle_open_search_modal(ack, body, client):
    """'검색하기' 버튼 클릭 시 Modal을 연다."""
    await ack()
    trigger_id = body["trigger_id"]
    await client.views_open(trigger_id=trigger_id, view=SEARCH_MODAL)


# ---------------------------------------------------------------------------
# Modal 제출 핸들러
# ---------------------------------------------------------------------------



async def handle_search_modal_submit(ack, body, client):
    """Modal 제출 시 검색을 실행한다.

    팀원이 만든 handle_project_search를 재활용한다.
    """
    await ack()

    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]

    # 입력값 추출
    category = values["category_block"]["category_select"]["selected_option"]["value"]
    project_name = values["project_block"]["project_input"]["value"]

    # 기간 처리
    date_preset = values["date_preset_block"]["date_preset_select"]["selected_option"]["value"]
    date_from, date_to = _resolve_date_range(date_preset, values)

    # 직접 입력 기간 처리
    custom_date_text = None
    if date_to == "__custom__":
        custom_date_text = date_from
        date_from, date_to = None, None

    # 직접 입력 기간이 있으면 AI 의도 분류로 날짜 파싱
    if custom_date_text:
        from app.ai.summarizer import classify_intent
        date_query = f"{project_name} {custom_date_text}"
        intent_result = await classify_intent(date_query)
        date_from = intent_result.get("date_from")
        date_to = intent_result.get("date_to")

    slack_client = AsyncWebClient(token=settings.slack_bot_token)

    # 검색 중 메시지
    period_text = ""
    if custom_date_text:
        period_text = f" | 📅 {custom_date_text}"
    elif date_from and date_to:
        period_text = f" | 📅 {date_from} ~ {date_to}"
    await slack_client.chat_postMessage(
        channel=user_id,
        text=f"🔍 *{project_name}* 검색 중... ({_category_label(category)}{period_text})",
    )

    # 프로젝트명을 리스트로 변환 (쉼표 구분 지원)
    project_names = [p.strip() for p in project_name.split(",") if p.strip()]

    # handlers.py의 handle_project_search 호출
    from app.slack.handlers import handle_project_search

    async def say_via_api(text=None, blocks=None, **kwargs):
        """Modal에서는 say가 없으므로 API로 대체한다."""
        await slack_client.chat_postMessage(
            channel=user_id,
            text=text or "",
            blocks=blocks,
        )

    await handle_project_search(
        user_id=user_id,
        project_names=project_names,
        category=category,
        date_from=date_from,
        date_to=date_to,
        say=say_via_api,
    )


def _resolve_date_range(preset: str, values: dict) -> tuple[str | None, str | None]:
    """기간 드롭다운 또는 직접 입력에서 date_from, date_to를 계산한다."""
    today = datetime.now(timezone.utc).date()

    if preset == "custom":
        # 직접 입력 텍스트가 있으면 AI에게 파싱을 맡기기 위해 None 반환
        # (프로젝트명에 기간 텍스트를 붙여서 classify_intent로 처리)
        custom_block = values.get("date_custom_block")
        if custom_block:
            custom_text = custom_block.get("date_custom_input", {}).get("value")
            if custom_text:
                # 직접 입력은 별도 처리 — caller에서 keyword에 붙임
                return custom_text, "__custom__"
        return None, None

    presets = {
        "all": None,
        "1w": timedelta(weeks=1),
        "1m": timedelta(days=30),
        "3m": timedelta(days=90),
        "6m": timedelta(days=180),
        "1y": timedelta(days=365),
    }

    delta = presets.get(preset)
    if delta is None:
        return None, None

    date_from = (today - delta).isoformat()
    date_to = today.isoformat()
    return date_from, date_to


def _category_label(category: str) -> str:
    """카테고리 value를 한국어 라벨로 변환한다."""
    return {"business": "📋 사업", "development": "💻 개발"}.get(category, category)


# ---------------------------------------------------------------------------
# bot.py에 등록할 함수
# ---------------------------------------------------------------------------

def register_modal_handlers(app):
    """Slack app에 Modal 관련 핸들러를 등록한다.

    bot.py에서 한 줄로 호출:
        from app.slack.modal import register_modal_handlers
        register_modal_handlers(slack_app)
    """
    app.action("open_search_modal")(handle_open_search_modal)
    app.action("date_preset_select")(handle_date_preset_change)
    app.view("search_modal_submit")(handle_search_modal_submit)
