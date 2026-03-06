from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import DEFAULT_MINIAPP_URL
from bot.constants import (
    MENU_AI_CODE,
    MENU_AI_CHAT,
    MENU_AI_DEEPSEEK,
    MENU_AI_IMAGE,
    MENU_AI_KIMI,
    MENU_AI_PROMPT,
    MENU_AI_RESEARCH,
    MENU_AI_TOOLS,
    MENU_CALCULATOR,
    MENU_CANCEL,
    MENU_GAMES,
    MENU_HELP,
    MENU_UTILITIES,
    MENU_VERSION_MODELS,
)


def main_menu_keyboard(miniapp_url: str | None = None) -> ReplyKeyboardMarkup:
    _ = miniapp_url
    rows = [[KeyboardButton(text="Open App", web_app=WebAppInfo(url=DEFAULT_MINIAPP_URL))]]

    rows.extend([
        [KeyboardButton(text=MENU_AI_TOOLS), KeyboardButton(text=MENU_UTILITIES)],
        [KeyboardButton(text=MENU_HELP), KeyboardButton(text=MENU_VERSION_MODELS)],
        [KeyboardButton(text=MENU_CANCEL)],
    ])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="🧠 Ask me anything or pick a feature",
    )


def ai_tools_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MENU_AI_CHAT), KeyboardButton(text=MENU_AI_CODE)],
        [KeyboardButton(text=MENU_AI_RESEARCH), KeyboardButton(text=MENU_AI_PROMPT)],
        [KeyboardButton(text=MENU_AI_IMAGE), KeyboardButton(text=MENU_AI_DEEPSEEK)],
        [KeyboardButton(text=MENU_AI_KIMI)],
        [KeyboardButton(text=MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="🤖 Pick an AI mode",
    )


def utilities_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MENU_CALCULATOR)],
        [KeyboardButton(text=MENU_GAMES)],
        [KeyboardButton(text=MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="🛠️ Pick a utility tool",
    )


def games_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌⭕ Tic-Tac-Toe", callback_data="gm:ttt")
    builder.button(text="🎯 Guess the Number", callback_data="gm:guess")
    builder.button(text="🏠 Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()
