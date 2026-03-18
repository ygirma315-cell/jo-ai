from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _append_back_main(builder: InlineKeyboardBuilder, back_callback: str, back_text: str = "⬅️ Back") -> None:
    builder.button(text=back_text, callback_data=back_callback)
    builder.button(text="🏠 Main Menu", callback_data="menu:main")


def jo_ai_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 JO AI Chat", callback_data="joai:chat")
    builder.button(text="⚡ Code Generator", callback_data="joai:code")
    builder.button(text="🔍 Research", callback_data="joai:research")
    builder.button(text="🧠 DeepSeek", callback_data="joai:deep_analysis")
    builder.button(text="✨ Prompt Generator", callback_data="joai:prompt")
    builder.button(text="🎨 Image Generation", callback_data="joai:image")
    builder.button(text="🎬 Video Generation", callback_data="joai:video")
    builder.button(text="🖼️ Vision", callback_data="joai:kimi")
    builder.button(text="🔊 Text-to-Speech", callback_data="joai:tts")
    builder.button(text="GPT Audio", callback_data="joai:gpt_audio")
    _append_back_main(builder, "menu:ai_tools")
    builder.adjust(2, 2, 2, 2, 2, 2)
    return builder.as_markup()


def jo_chat_keyboard(back_callback: str = "joai:menu", back_text: str = "⬅️ Back") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _append_back_main(builder, back_callback, back_text)
    builder.adjust(2)
    return builder.as_markup()


def gemini_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Chat", callback_data="joaigem:mode:chat")
    builder.button(text="🎨 Image", callback_data="joaigem:mode:image")
    builder.button(text="🔊 Voice", callback_data="joaigem:mode:voice")
    _append_back_main(builder, "joai:menu")
    builder.adjust(3, 2)
    return builder.as_markup()


def kimi_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Try Again", callback_data="joai:kimi_retry")
    _append_back_main(builder, "joai:kimi")
    builder.adjust(1, 2)
    return builder.as_markup()


def uploaded_image_keyboard(back_callback: str = "menu:ai_tools") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼️ Describe Image", callback_data="joai:kimi_describe_last")
    _append_back_main(builder, back_callback)
    builder.adjust(1, 2)
    return builder.as_markup()


def image_ratio_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="1:1", callback_data="joaiimg:ratio:1_1")
    builder.button(text="16:9", callback_data="joaiimg:ratio:16_9")
    builder.button(text="9:16", callback_data="joaiimg:ratio:9_16")
    builder.button(text="🧩 Model", callback_data="joaiimg:model_menu")
    _append_back_main(builder, "joai:image")
    builder.adjust(2, 1, 1, 2)
    return builder.as_markup()


def image_model_keyboard(
    selected_model: str | None = None,
    model_options: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    selected = (selected_model or "").strip().lower()
    options = model_options or [("JO AI Image Generate", "joai_image_generate")]
    builder = InlineKeyboardBuilder()
    for label, token in options:
        prefix = "✅ " if token == selected else ""
        builder.button(text=f"{prefix}{label}", callback_data=f"joaiimg:model:{token}")
    _append_back_main(builder, "joaiimg:ratio_menu")
    layout = [1] * len(options)
    layout.append(2)
    builder.adjust(*layout)
    return builder.as_markup()


def video_options_keyboard(
    selected_duration_seconds: int | None = None,
    selected_aspect_ratio: str | None = None,
) -> InlineKeyboardMarkup:
    duration = int(selected_duration_seconds or 4)
    ratio = (selected_aspect_ratio or "16:9").strip()
    duration_options = (4, 6, 8)
    ratio_options: tuple[tuple[str, str], ...] = (("16:9", "16_9"), ("9:16", "9_16"))

    builder = InlineKeyboardBuilder()
    for value in duration_options:
        prefix = "✅ " if value == duration else ""
        builder.button(text=f"{prefix}{value}s", callback_data=f"joaivid:duration:{value}")
    for label, token in ratio_options:
        prefix = "✅ " if label == ratio else ""
        builder.button(text=f"{prefix}{label}", callback_data=f"joaivid:ratio:{token}")
    builder.button(text="🎬 Generate Video", callback_data="joaivid:generate")
    _append_back_main(builder, "joai:video")
    builder.adjust(3, 2, 1, 2)
    return builder.as_markup()


def tts_language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇬🇧 English", callback_data="joaitts:lang:en")
    builder.button(text="🇪🇸 Spanish", callback_data="joaitts:lang:es")
    builder.button(text="🇫🇷 French", callback_data="joaitts:lang:fr")
    _append_back_main(builder, "joai:menu")
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def tts_voice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎙️ Female", callback_data="joaitts:voice:female")
    builder.button(text="🎙️ Male", callback_data="joaitts:voice:male")
    builder.button(text="🧬 Voice Clone", callback_data="joaitts:clone")
    _append_back_main(builder, "joaitts:lang_menu")
    builder.adjust(2, 1, 2)
    return builder.as_markup()


def tts_style_keyboard(style_buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, style_key in style_buttons:
        builder.button(text=label, callback_data=f"joaitts:style:{style_key}")
    builder.button(text="🧬 Voice Clone", callback_data="joaitts:clone")
    _append_back_main(builder, "joaitts:voice_menu")
    layout = [2] * (len(style_buttons) // 2)
    if len(style_buttons) % 2:
        layout.append(1)
    layout.extend([1, 2])
    builder.adjust(*layout)
    return builder.as_markup()
