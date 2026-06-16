from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.config import DEFAULT_MINIAPP_URL
from bot.constants import (
    MENU_AI_CODE,
    MENU_AI_CHAT,
    MENU_AI_HEAR,
    MENU_AI_IMAGE,
    MENU_AI_IMAGE_EDIT,
    MENU_AI_KIMI,
    MENU_AI_TTS,
    MENU_AI_TOOLS,
    MENU_CANCEL,
    MENU_HELP,
    MENU_REFERRAL,
    MENU_VERSION_MODELS,
)


def main_menu_keyboard(miniapp_url: str | None = None) -> ReplyKeyboardMarkup:
    _ = miniapp_url
    rows = [
        [
            KeyboardButton(text=MENU_AI_TOOLS),
            KeyboardButton(text="🚀 Open App", web_app=WebAppInfo(url=DEFAULT_MINIAPP_URL)),
        ],
        [KeyboardButton(text=MENU_REFERRAL), KeyboardButton(text=MENU_HELP)],
        [KeyboardButton(text=MENU_VERSION_MODELS)],
        [KeyboardButton(text=MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Ask me anything or pick a feature",
    )


def join_channel_keyboard(channel_url: str | None) -> InlineKeyboardMarkup | None:
    resolved_url = str(channel_url or "").strip()
    if not resolved_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Join Main Channel", url=resolved_url)],
        ]
    )


def ai_tools_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MENU_AI_CHAT), KeyboardButton(text=MENU_AI_CODE)],
        [KeyboardButton(text=MENU_AI_IMAGE), KeyboardButton(text=MENU_AI_IMAGE_EDIT)],
        [KeyboardButton(text=MENU_AI_KIMI), KeyboardButton(text=MENU_AI_TTS)],
        [KeyboardButton(text=MENU_AI_HEAR)],
        [KeyboardButton(text=MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Pick an AI mode",
    )
