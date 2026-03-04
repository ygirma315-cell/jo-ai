from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def jo_ai_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="JO AI Chat", callback_data="joai:chat")
    builder.button(text="Code Generator", callback_data="joai:code")
    builder.button(text="Research", callback_data="joai:research")
    builder.button(text="Prompt Generator", callback_data="joai:prompt")
    builder.button(text="Image Generator", callback_data="joai:image")
    builder.button(text="Kimi Image Describer", callback_data="joai:kimi")
    builder.button(text="Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def jo_chat_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Switch Mode", callback_data="joai:menu")
    builder.button(text="Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def kimi_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Try Again (same image)", callback_data="joai:kimi_retry")
    builder.button(text="Switch Mode", callback_data="joai:menu")
    builder.button(text="Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def jo_ai_image_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Switch Mode", callback_data="joai:menu")
    builder.button(text="Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def image_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Realistic Image", callback_data="joaiimg:type:realistic")
    builder.button(text="AI Art", callback_data="joaiimg:type:ai_art")
    builder.button(text="Anime Style", callback_data="joaiimg:type:anime")
    builder.button(text="Cyberpunk Style", callback_data="joaiimg:type:cyberpunk")
    builder.button(text="Logo / Icon", callback_data="joaiimg:type:logo_icon")
    builder.button(text="3D Render", callback_data="joaiimg:type:render_3d")
    builder.button(text="Concept Art", callback_data="joaiimg:type:concept_art")
    builder.button(text="Back to AI Tools", callback_data="joai:menu")
    builder.adjust(1)
    return builder.as_markup()


def deepseek_model_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="DeepSeek Thinking", callback_data="joaimodel:deepseek_thinking")
    builder.button(text="DeepSeek Reasoning", callback_data="joaimodel:deepseek_reasoning")
    builder.button(text="Back to AI Tools", callback_data="joai:menu")
    builder.adjust(1)
    return builder.as_markup()
