from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def jo_ai_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001F4AC JO AI Chat", callback_data="joai:chat")
    builder.button(text="\u26A1 Code Generator", callback_data="joai:code")
    builder.button(text="\U0001F50D Research", callback_data="joai:research")
    builder.button(text="\U0001F9E0 Deep Analysis", callback_data="joai:deep_analysis")
    builder.button(text="\u2728 Prompt Generator", callback_data="joai:prompt")
    builder.button(text="\U0001F3A8 Image Generator", callback_data="joai:image")
    builder.button(text="\U0001F5BC\ufe0f Vision", callback_data="joai:kimi")
    builder.button(text="\U0001F50A Text-to-Speech", callback_data="joai:tts")
    builder.button(text="\U0001F3E0 Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def jo_chat_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001F504 Switch Mode", callback_data="joai:menu")
    builder.button(text="\U0001F3E0 Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def kimi_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001F501 Try Again (same image)", callback_data="joai:kimi_retry")
    builder.button(text="\U0001F504 Switch Mode", callback_data="joai:menu")
    builder.button(text="\U0001F3E0 Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def jo_ai_image_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001F504 Switch Mode", callback_data="joai:menu")
    builder.button(text="\U0001F3E0 Back to Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def image_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001F4F8 Realistic Image", callback_data="joaiimg:type:realistic")
    builder.button(text="\U0001FA84 AI Art", callback_data="joaiimg:type:ai_art")
    builder.button(text="\U0001F338 Anime Style", callback_data="joaiimg:type:anime")
    builder.button(text="\U0001F303 Cyberpunk Style", callback_data="joaiimg:type:cyberpunk")
    builder.button(text="\U0001F9E9 Logo / Icon", callback_data="joaiimg:type:logo_icon")
    builder.button(text="\U0001F9F1 3D Render", callback_data="joaiimg:type:render_3d")
    builder.button(text="\U0001F58C\ufe0f Concept Art", callback_data="joaiimg:type:concept_art")
    builder.button(text="\u21A9\ufe0f Back to AI Tools", callback_data="joai:menu")
    builder.adjust(1)
    return builder.as_markup()


def image_ratio_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="1:1", callback_data="joaiimg:ratio:1_1")
    builder.button(text="16:9", callback_data="joaiimg:ratio:16_9")
    builder.button(text="9:16", callback_data="joaiimg:ratio:9_16")
    builder.button(text="\u21A9\ufe0f Back to image styles", callback_data="joai:image")
    builder.adjust(1)
    return builder.as_markup()


def tts_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="English", callback_data="joaitts:lang:en")
    builder.button(text="Spanish", callback_data="joaitts:lang:es")
    builder.button(text="French", callback_data="joaitts:lang:fr")
    builder.button(text="\u21A9\ufe0f Back to AI Tools", callback_data="joai:menu")
    builder.adjust(1)
    return builder.as_markup()


def tts_voice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Female", callback_data="joaitts:voice:female")
    builder.button(text="Male", callback_data="joaitts:voice:male")
    builder.button(text="\u21A9\ufe0f Back to language", callback_data="joaitts:lang_menu")
    builder.adjust(1)
    return builder.as_markup()


def tts_emotion_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Neutral", callback_data="joaitts:emotion:neutral")
    builder.button(text="Cheerful", callback_data="joaitts:emotion:cheerful")
    builder.button(text="Calm", callback_data="joaitts:emotion:calm")
    builder.button(text="Serious", callback_data="joaitts:emotion:serious")
    builder.button(text="\u21A9\ufe0f Back to voice", callback_data="joaitts:voice_menu")
    builder.adjust(1)
    return builder.as_markup()
