from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.config import DEFAULT_MINIAPP_URL
from bot.constants import (
    MENU_AI_CODE,
    MENU_AI_CHAT,
    MENU_AI_DEEPSEEK,
    MENU_AI_IMAGE,
    MENU_AI_KIMI,
    MENU_AI_PROMPT,
    MENU_AI_RESEARCH,
    MENU_AI_TTS,
    MENU_AI_TOOLS,
    MENU_CANCEL,
    MENU_HELP,
    MENU_VERSION_MODELS,
)


def main_menu_keyboard(miniapp_url: str | None = None) -> ReplyKeyboardMarkup:
    _ = miniapp_url
    rows = [
        [
            KeyboardButton(text=MENU_AI_TOOLS),
            KeyboardButton(text="🚀 Open App", web_app=WebAppInfo(url=DEFAULT_MINIAPP_URL)),
        ],
        [KeyboardButton(text=MENU_HELP), KeyboardButton(text=MENU_VERSION_MODELS)],
        [KeyboardButton(text=MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Ask me anything or pick a feature",
    )


def ai_tools_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MENU_AI_CHAT), KeyboardButton(text=MENU_AI_CODE)],
        [KeyboardButton(text=MENU_AI_RESEARCH), KeyboardButton(text=MENU_AI_PROMPT)],
        [KeyboardButton(text=MENU_AI_IMAGE), KeyboardButton(text=MENU_AI_DEEPSEEK)],
        [KeyboardButton(text=MENU_AI_KIMI), KeyboardButton(text=MENU_AI_TTS)],
        [KeyboardButton(text=MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Pick an AI mode",
    )
