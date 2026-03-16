from __future__ import annotations

from contextlib import suppress
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.models.session import Feature
from bot.services.session_manager import SessionManager
from bot.services.tracking_service import SupabaseTrackingService

logger = logging.getLogger(__name__)
BLOCKED_ACCESS_NOTICE = "Your access to this bot is currently restricted. Contact support for help."
BLOCKED_ACCESS_ALERT = "Access restricted."


class UserActionLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = None
        username = None
        first_name = None
        action = None
        payload = None

        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username
            first_name = event.from_user.first_name
            action = "message"
            payload = event.text or event.caption or ""
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username
            first_name = event.from_user.first_name
            action = "callback"
            payload = event.data or ""

        tracking_service = data.get("tracking_service")
        if (
            user_id is not None
            and isinstance(tracking_service, SupabaseTrackingService)
            and tracking_service.enabled
        ):
            try:
                restricted = await tracking_service.is_user_access_restricted(int(user_id))
            except Exception:
                logger.warning("USER ACCESS CHECK FAILED user_id=%s", user_id, exc_info=True)
                restricted = False
            if restricted:
                logger.warning(
                    "BLOCKED USER ACCESS DENIED | user_id=%s username=%s action=%s",
                    user_id,
                    username,
                    action,
                )
                if isinstance(event, Message):
                    await event.answer(BLOCKED_ACCESS_NOTICE)
                elif isinstance(event, CallbackQuery):
                    with suppress(Exception):
                        await event.answer(BLOCKED_ACCESS_ALERT, show_alert=True)
                    if isinstance(event.message, Message):
                        await event.message.answer(BLOCKED_ACCESS_NOTICE)
                return None

        session_manager: SessionManager | None = data.get("session_manager")
        feature: Feature | None = None
        if session_manager and user_id is not None:
            session_manager.remember_user(user_id)
            feature = session_manager.get_active_feature(user_id)

        if user_id is not None:
            compact_payload = payload[:200] if payload else ""
            logger.info(
                "RECEIVED UPDATE | action=%s user_id=%s username=%s payload=%s",
                action,
                user_id,
                username,
                compact_payload,
            )
            logger.info(
                "User action: id=%s username=%s first_name=%s action=%s payload=%s feature=%s",
                user_id,
                username,
                first_name,
                action,
                payload,
                feature.value if feature else None,
            )

        return await handler(event, data)
