from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.services.tracking_service import SupabaseTrackingService, TrackingIdentity

logger = logging.getLogger(__name__)

GROUP_COMMANDS_TEXT = (
    "<b>JO AI group commands</b>\n\n"
    "<code>/start</code> - show this list\n"
    "<code>/ask what is AI?</code> - ask JO AI a question\n"
    "<code>/search what is AI?</code> - ask JO AI a question\n"
    "<code>/image cat</code> - generate an image\n"
    "<code>/audio say hello</code> - generate audio\n\n"
    "Tip: in groups, use the prompt in the same command message, like "
    "<code>/image sunset over Addis Ababa</code>."
)


def group_tracking_identity(chat: Any) -> TrackingIdentity | None:
    chat_type = str(getattr(chat, "type", "") or "").strip().lower()
    if chat_type not in {"group", "supergroup"}:
        return None
    try:
        chat_id = int(getattr(chat, "id", 0) or 0)
    except (TypeError, ValueError):
        return None
    if chat_id == 0:
        return None
    title = str(getattr(chat, "title", "") or "").strip() or None
    username = str(getattr(chat, "username", "") or "").strip() or None
    return TrackingIdentity(
        telegram_id=chat_id,
        username=username,
        first_name=title,
        last_name=None,
    )


async def track_group_chat(
    tracking_service: SupabaseTrackingService | None,
    chat: Any,
    *,
    feature_used: str,
    bot_reply: str | None = None,
) -> None:
    if tracking_service is None or not tracking_service.enabled:
        return
    identity = group_tracking_identity(chat)
    if identity is None:
        return
    safe_feature = str(feature_used or "group_seen").strip().lower() or "group_seen"
    try:
        await asyncio.wait_for(
            tracking_service.track_action(
                identity=identity,
                message_type="group",
                user_message=f"Group seen: {identity.first_name or identity.telegram_id}",
                bot_reply=bot_reply,
                model_used=None,
                success=True,
                frontend_source="telegram_bot",
                feature_used=safe_feature,
                conversation_id=f"{identity.telegram_id}:group",
                text_content=identity.first_name or str(identity.telegram_id),
                mark_started=True,
            ),
            timeout=8,
        )
    except Exception:
        logger.warning("Failed to track Telegram group chat %s.", identity.telegram_id, exc_info=True)
