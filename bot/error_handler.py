from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, ErrorEvent, Message

logger = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent) -> bool:
    user_id = None
    username = None
    first_name = None
    update = event.update
    if update.message and update.message.from_user:
        user_id = update.message.from_user.id
        username = update.message.from_user.username
        first_name = update.message.from_user.first_name
    elif update.callback_query and update.callback_query.from_user:
        user_id = update.callback_query.from_user.id
        username = update.callback_query.from_user.username
        first_name = update.callback_query.from_user.first_name

    logger.error(
        "Update error (user_id=%s username=%s first_name=%s): %s",
        user_id,
        username,
        first_name,
        event.exception,
    )

    if update.message:
        await update.message.answer("Something went wrong. Please try again.")
        return True

    if update.callback_query:
        await update.callback_query.answer("Something went wrong. Please try again.", show_alert=True)
        if update.callback_query.message:
            await update.callback_query.message.answer("Something went wrong. Please try again.")
        return True

    return True


def register_error_handler(dispatcher: Dispatcher) -> None:
    dispatcher.errors.register(global_error_handler)
