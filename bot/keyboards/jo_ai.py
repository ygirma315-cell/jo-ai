from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _append_back_main(builder: InlineKeyboardBuilder, back_callback: str, back_text: str = "Back") -> None:
    builder.button(text=back_text, callback_data=back_callback)
    builder.button(text="Main Menu", callback_data="menu:main")


def jo_ai_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="JO AI Chat", callback_data="joai:chat")
    builder.button(text="Code Generator", callback_data="joai:code")
    builder.button(text="Research", callback_data="joai:research")
    builder.button(text="Deep Analysis", callback_data="joai:deep_analysis")
    builder.button(text="Prompt Generator", callback_data="joai:prompt")
    builder.button(text="Image Generator", callback_data="joai:image")
    builder.button(text="Vision", callback_data="joai:kimi")
    builder.button(text="Text-to-Speech", callback_data="joai:tts")
    _append_back_main(builder, "menu:ai_tools")
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()


def jo_chat_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _append_back_main(builder, "joai:menu")
    builder.adjust(2)
    return builder.as_markup()


def kimi_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Try Again", callback_data="joai:kimi_retry")
    _append_back_main(builder, "joai:kimi")
    builder.adjust(1, 2)
    return builder.as_markup()


def uploaded_image_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Describe Image", callback_data="joai:kimi_describe_last")
    _append_back_main(builder, "menu:ai_tools")
    builder.adjust(1, 2)
    return builder.as_markup()


def image_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Realistic", callback_data="joaiimg:type:realistic")
    builder.button(text="AI Art", callback_data="joaiimg:type:ai_art")
    builder.button(text="Anime", callback_data="joaiimg:type:anime")
    builder.button(text="Cyberpunk", callback_data="joaiimg:type:cyberpunk")
    builder.button(text="Logo / Icon", callback_data="joaiimg:type:logo_icon")
    builder.button(text="3D Render", callback_data="joaiimg:type:render_3d")
    builder.button(text="Concept Art", callback_data="joaiimg:type:concept_art")
    _append_back_main(builder, "joai:menu")
    builder.adjust(2, 2, 2, 1, 2)
    return builder.as_markup()


def image_ratio_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="1:1", callback_data="joaiimg:ratio:1_1")
    builder.button(text="16:9", callback_data="joaiimg:ratio:16_9")
    builder.button(text="9:16", callback_data="joaiimg:ratio:9_16")
    _append_back_main(builder, "joai:image")
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def tts_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="English", callback_data="joaitts:lang:en")
    builder.button(text="Spanish", callback_data="joaitts:lang:es")
    builder.button(text="French", callback_data="joaitts:lang:fr")
    _append_back_main(builder, "joai:menu")
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def tts_voice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Female", callback_data="joaitts:voice:female")
    builder.button(text="Male", callback_data="joaitts:voice:male")
    builder.button(text="Voice Clone", callback_data="joaitts:clone")
    _append_back_main(builder, "joaitts:lang_menu")
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def tts_style_keyboard(style_buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, style_key in style_buttons:
        builder.button(text=label, callback_data=f"joaitts:style:{style_key}")
    builder.button(text="Voice Clone", callback_data="joaitts:clone")
    _append_back_main(builder, "joaitts:voice_menu")
    layout = [2] * (len(style_buttons) // 2)
    if len(style_buttons) % 2:
        layout.append(1)
    layout.extend([1, 2])
    builder.adjust(*layout)
    return builder.as_markup()
