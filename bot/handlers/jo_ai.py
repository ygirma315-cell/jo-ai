from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import html
import logging
import re
from contextlib import suppress
from typing import Literal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.constants import (
    MENU_AI_CHAT,
    MENU_AI_CODE,
    MENU_AI_DEEPSEEK,
    MENU_AI_GEMINI,
    MENU_AI_GPT_AUDIO,
    MENU_AI_IMAGE,
    MENU_AI_VIDEO,
    MENU_AI_KIMI,
    MENU_AI_PROMPT,
    MENU_AI_RESEARCH,
    MENU_AI_TTS,
    MENU_AI_TOOLS,
    MENU_BUTTON_TEXTS,
    MENU_JO_AI,
)
from bot.filters.feature_filter import ActiveFeatureFilter
from bot.keyboards.jo_ai import (
    gemini_mode_keyboard,
    image_model_keyboard,
    image_ratio_keyboard,
    jo_ai_menu_keyboard,
    jo_chat_keyboard,
    kimi_result_keyboard,
    video_options_keyboard,
    tts_language_keyboard,
    tts_style_keyboard,
    tts_voice_keyboard,
    uploaded_image_keyboard,
)
from bot.keyboards.menu import main_menu_keyboard
from bot.models.session import Feature, JoAIMode
from bot.security import (
    BRANDING_LINE,
    DEVELOPER_HANDLE,
    SAFE_INTERNAL_DETAILS_REFUSAL,
    SAFE_SERVICE_UNAVAILABLE_MESSAGE,
    guardrail_response_for_user_query,
)
from bot.services.ai_service import (
    AIServiceError,
    ChatService,
    GeminiChatService,
    ImageGenerationService,
    PollinationsMediaService,
    TextToSpeechService,
    build_enhanced_image_prompt,
    build_enhanced_video_prompt,
)
from bot.services.session_manager import SessionManager
from bot.services.tracking_service import SupabaseTrackingService, TrackingIdentity, TrackingMedia
from bot.telegram_formatting import TelegramMessageFormatter

router = Router(name="jo_ai")
logger = logging.getLogger(__name__)

JO_AI_MENU_TEXT = (
    "<b>JO AI Tools</b>\n\n"
    "Choose a mode:\n"
    "- JO AI Chat\n"
    "- Code Generator\n"
    "- Research\n"
    "- DeepSeek\n"
    "- Prompt Generator\n"
    "- Image Generation\n"
    "- Video Generation\n"
    "- JO AI Vision\n"
    "- Text-to-Speech\n\n"
    "- GPT Audio\n\n"
    "Tip: use /help any time for guidance."
)

IMAGE_RATIO_LABELS = {
    "1:1": "1:1",
    "16:9": "16:9",
    "9:16": "9:16",
}

IMAGE_RATIO_TOKEN_MAP = {
    "1_1": "1:1",
    "16_9": "16:9",
    "9_16": "9:16",
}

IMAGE_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "16:9": "1344x768",
    "9:16": "768x1344",
}

IMAGE_MODEL_OPTION_JO = "joai_image_generate"
IMAGE_MODEL_OPTION_CHAT_GBT = "chat_gbt"
IMAGE_MODEL_OPTION_GROK_IMAGINE = "grok_imagine"
DEFAULT_IMAGE_MODEL_OPTION = IMAGE_MODEL_OPTION_JO

IMAGE_MODEL_LABELS = {
    IMAGE_MODEL_OPTION_JO: "JO AI Image Generate",
    IMAGE_MODEL_OPTION_CHAT_GBT: "Chat GBT",
    IMAGE_MODEL_OPTION_GROK_IMAGINE: "Grok Imagine",
}

IMAGE_MODEL_ALIASES = {
    IMAGE_MODEL_OPTION_JO: IMAGE_MODEL_OPTION_JO,
    "jo ai image generate": IMAGE_MODEL_OPTION_JO,
    "jo_ai_image_generate": IMAGE_MODEL_OPTION_JO,
    "jo_ai": IMAGE_MODEL_OPTION_JO,
    "joai": IMAGE_MODEL_OPTION_JO,
    "chat gbt": IMAGE_MODEL_OPTION_CHAT_GBT,
    "chat_gbt": IMAGE_MODEL_OPTION_CHAT_GBT,
    IMAGE_MODEL_OPTION_CHAT_GBT: IMAGE_MODEL_OPTION_CHAT_GBT,
    "grok imagine": IMAGE_MODEL_OPTION_GROK_IMAGINE,
    "grok_imagine": IMAGE_MODEL_OPTION_GROK_IMAGINE,
    IMAGE_MODEL_OPTION_GROK_IMAGINE: IMAGE_MODEL_OPTION_GROK_IMAGINE,
}

VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO = "grok_text_to_video"
VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO = "Grok Text to Video"
DEFAULT_VIDEO_DURATION_SECONDS = 4
DEFAULT_VIDEO_ASPECT_RATIO = "16:9"
VIDEO_ASPECT_RATIO_TOKEN_MAP = {
    "16_9": "16:9",
    "9_16": "9:16",
}
VIDEO_ASPECT_RATIO_OPTIONS = {"16:9", "9:16"}
VIDEO_DURATION_OPTIONS = {4, 6, 8}
TELEGRAM_VIDEO_TIMEOUT_SECONDS = 220
VIDEO_JOIN_CHANNEL_USERNAME = "@JO_AI_CHAT_BOT"
VIDEO_JOIN_CHANNEL_URL = "https://t.me/JO_AI_CHAT_BOT"
VIDEO_ALLOWED_MEMBERSHIP_STATUSES = {"creator", "administrator", "member", "restricted"}
GPT_AUDIO_MODEL_LABEL = "GPT Audio"
GPT_AUDIO_TIMEOUT_SECONDS = 120

TTS_LANGUAGE_LABELS = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
}

TTS_VOICE_LABELS = {
    "female": "Female",
    "male": "Male",
}

TTS_EMOTION_LABELS = {
    "neutral": "Neutral",
    "cheerful": "Cheerful",
    "calm": "Calm",
    "serious": "Serious",
}


def _video_join_required_text() -> str:
    return (
        "Please join the JO AI channel first to use Video Generation.\n"
        f"Join here: {VIDEO_JOIN_CHANNEL_URL}\n"
        "After joining, try Video Generation again."
    )


def _video_join_required_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✈️ Join JO AI Channel", url=VIDEO_JOIN_CHANNEL_URL)],
            [InlineKeyboardButton(text="Joined ✅", callback_data="joaivid:joined_check")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="joai:menu")],
        ]
    )


async def _is_video_generation_allowed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=VIDEO_JOIN_CHANNEL_USERNAME, user_id=user_id)
    except Exception:
        logger.warning("Video membership check failed for user=%s", user_id, exc_info=True)
        return False
    status = str(getattr(member, "status", "")).strip().lower()
    return status in VIDEO_ALLOWED_MEMBERSHIP_STATUSES


def _resolve_image_model_option(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in IMAGE_MODEL_ALIASES:
        return IMAGE_MODEL_ALIASES[candidate]
    return DEFAULT_IMAGE_MODEL_OPTION


def _image_model_label(model_option: str | None) -> str:
    normalized = _resolve_image_model_option(model_option)
    return IMAGE_MODEL_LABELS.get(normalized, IMAGE_MODEL_LABELS[DEFAULT_IMAGE_MODEL_OPTION])

TTS_STYLE_PRESETS: dict[str, dict[str, dict[str, str]]] = {
    "female": {
        "natural": {"label": "Natural", "emotion": "neutral"},
        "warm": {"label": "Warm", "emotion": "calm"},
        "soft": {"label": "Soft", "emotion": "calm"},
        "bright": {"label": "Bright", "emotion": "cheerful"},
        "narrator": {"label": "Narrator", "emotion": "serious"},
        "formal": {"label": "Formal", "emotion": "serious"},
    },
    "male": {
        "natural": {"label": "Natural", "emotion": "neutral"},
        "deep": {"label": "Deep", "emotion": "serious"},
        "calm": {"label": "Calm", "emotion": "calm"},
        "friendly": {"label": "Friendly", "emotion": "neutral"},
        "energetic": {"label": "Energetic", "emotion": "cheerful"},
        "narrator": {"label": "Narrator", "emotion": "serious"},
    },
}

ENGAGEMENT_LINES = (
    "Thinking...",
    "Analyzing your request...",
    "Optimizing the response...",
    "Crafting a clean answer...",
)

MODE_PROGRESS_TEXT = {
    "chat": "Thinking about your message...",
    "code": "Generating code...",
    "research": "Researching your topic...",
    "prompt": "Building your prompt...",
    "image_prompt": "Optimizing image prompt...",
}

MODE_RESULT_TITLE = {
    "chat": "JO AI Reply",
    "code": "Code Result",
    "research": "Research Result",
    "prompt": "Prompt Result",
    "image_prompt": "Image Prompt Result",
}

MAX_REPLY_CHARS = 3300
CODE_FENCE_PATTERN = re.compile(r"```(?P<lang>[a-zA-Z0-9_+#.-]*)\n(?P<code>[\s\S]*?)```", re.MULTILINE)
CHAT_HISTORY_ENTRY_MAX_CHARS = 1800
LONG_CODE_ATTACHMENT_THRESHOLD = 2800
EXTREME_CODE_LENGTH_THRESHOLD = 16000
MAX_CODE_UPLOAD_BYTES = 1_500_000
TELEGRAM_TRACKING_TIMEOUT_SECONDS = 4.0
TELEGRAM_IMAGE_TIMEOUT_SECONDS = 120
GEMINI_TEMP_DISABLED = True
DEBUG_INTENT_PATTERN = re.compile(
    r"\b(debug|fix|error|exception|traceback|bug|issue|crash|failing|failure|broken|not working)\b",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class ParsedCodeReply:
    title: str
    explanation_lines: list[str]
    code: str
    lang: str
    run_steps: list[str]
    notes_lines: list[str]


def _default_mode_options() -> dict[str, object]:
    return {
        "model_override": None,
        "api_key_override": None,
        "thinking": False,
        "mode_prefix": "",
    }


def _deep_analysis_mode_options(deepseek_api_key: str | None, deepseek_model: str) -> dict[str, object]:
    mode_options = _default_mode_options()
    mode_options["thinking"] = True
    mode_options["mode_prefix"] = (
        "Deep analysis mode: think carefully, consider tradeoffs, then provide a clear final answer."
    )
    if (deepseek_api_key or "").strip():
        mode_options["api_key_override"] = deepseek_api_key
        mode_options["model_override"] = deepseek_model
    return mode_options


def _tracking_identity_from_message(message: Message) -> TrackingIdentity | None:
    user = message.from_user
    if user is None or int(user.id) <= 0:
        return None
    return TrackingIdentity(
        telegram_id=int(user.id),
        username=(user.username or "").strip() or None,
        first_name=(user.first_name or "").strip() or None,
        last_name=(user.last_name or "").strip() or None,
    )


def _tracking_text_from_message(message: Message, fallback: str) -> str:
    text = (message.text or message.caption or "").strip()
    if text:
        return text
    if message.document:
        name = (message.document.file_name or "").strip() or "document"
        return f"[document:{name}]"
    if message.photo:
        return "[photo]"
    return fallback


def _chat_model_used(chat_service: ChatService, mode_options: dict[str, object]) -> str | None:
    model_override = str(mode_options.get("model_override") or "").strip()
    if model_override:
        return model_override
    default_model = str(chat_service.model or "").strip()
    return default_model or None


async def _track_telegram_action(
    *,
    tracking_service: SupabaseTrackingService | None,
    message: Message,
    message_type: str,
    user_message: str,
    bot_reply: str | None,
    model_used: str | None,
    success: bool,
    message_increment: int = 0,
    image_increment: int = 0,
    frontend_source: str = "telegram_bot",
    feature_used: str | None = None,
    conversation_id: str | None = None,
    text_content: str | None = None,
    media: TrackingMedia | None = None,
    mark_started: bool = False,
    started_via_referral: str | None = None,
) -> None:
    identity = _tracking_identity_from_message(message)
    user_for_logs: int | str = identity.telegram_id if identity is not None else "unknown"
    logger.info("TELEGRAM TRACKING START user=%s message_type=%s", user_for_logs, message_type)

    if identity is None:
        logger.warning(
            "TELEGRAM TRACKING FAILED user=unknown message_type=%s error=missing telegram identity",
            message_type,
        )
        return
    if tracking_service is None:
        logger.warning(
            "TELEGRAM TRACKING FAILED user=%s message_type=%s error=tracking service unavailable",
            identity.telegram_id,
            message_type,
        )
        return
    if not tracking_service.enabled:
        logger.warning(
            "TELEGRAM TRACKING FAILED user=%s message_type=%s error=tracking disabled reason=%s",
            identity.telegram_id,
            message_type,
            tracking_service.disabled_reason or "unknown",
        )
        return

    effective_feature_used = (feature_used or message_type or "unknown").strip().lower()
    effective_media = media
    if effective_media is None and message.photo:
        largest = message.photo[-1]
        effective_media = TrackingMedia(
            media_type="image",
            storage_path=f"telegram_file:{largest.file_id}",
            mime_type="image/jpeg",
            provider_source="telegram",
            media_origin="upload",
            media_status="available",
        )
    if effective_media is None and message.document and str(message.document.mime_type or "").lower().startswith("image/"):
        effective_media = TrackingMedia(
            media_type="image",
            storage_path=f"telegram_file:{message.document.file_id}",
            mime_type=(message.document.mime_type or "").strip() or None,
            provider_source="telegram",
            media_origin="upload",
            media_status="available",
        )

    try:
        users_upserted, history_inserted = await asyncio.wait_for(
            tracking_service.track_action(
                identity=identity,
                message_type=message_type,
                user_message=user_message,
                bot_reply=bot_reply,
                model_used=model_used,
                success=success,
                message_increment=message_increment,
                image_increment=image_increment,
                frontend_source=frontend_source,
                feature_used=effective_feature_used,
                conversation_id=conversation_id or f"{identity.telegram_id}:{message.chat.id}",
                text_content=text_content or bot_reply or user_message,
                media=effective_media,
                mark_started=mark_started,
                started_via_referral=started_via_referral,
            ),
            timeout=TELEGRAM_TRACKING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "TELEGRAM TRACKING FAILED user=%s message_type=%s error=timeout_after_%ss",
            identity.telegram_id,
            message_type,
            TELEGRAM_TRACKING_TIMEOUT_SECONDS,
        )
        return
    except Exception as exc:
        logger.exception(
            "TELEGRAM TRACKING FAILED user=%s message_type=%s error=%s",
            identity.telegram_id,
            message_type,
            exc,
        )
        return

    if users_upserted > 0:
        logger.info("TELEGRAM USERS UPSERT SUCCESS user=%s rows=%s", identity.telegram_id, users_upserted)
    else:
        logger.warning(
            "TELEGRAM TRACKING FAILED user=%s message_type=%s error=users upsert returned zero rows",
            identity.telegram_id,
            message_type,
        )
    if history_inserted > 0:
        logger.info("TELEGRAM HISTORY INSERT SUCCESS user=%s rows=%s", identity.telegram_id, history_inserted)
    else:
        logger.warning(
            "TELEGRAM TRACKING FAILED user=%s message_type=%s error=history insert returned zero rows",
            identity.telegram_id,
            message_type,
        )


def _tts_style_choices(voice: str) -> list[tuple[str, str]]:
    presets = TTS_STYLE_PRESETS.get((voice or "").strip().lower(), TTS_STYLE_PRESETS["female"])
    return [(str(config.get("label", style_key)).strip(), style_key) for style_key, config in presets.items()]


def _tts_style_label(voice: str | None, style: str | None) -> str:
    voice_key = (voice or "").strip().lower()
    style_key = (style or "").strip().lower()
    preset = TTS_STYLE_PRESETS.get(voice_key, {}).get(style_key)
    if not preset:
        return "Natural"
    return str(preset.get("label", "Natural"))


def _tts_style_emotion(voice: str | None, style: str | None) -> str | None:
    voice_key = (voice or "").strip().lower()
    style_key = (style or "").strip().lower()
    preset = TTS_STYLE_PRESETS.get(voice_key, {}).get(style_key)
    if not preset:
        return None
    return str(preset.get("emotion", "")).strip().lower() or None


async def _show_jo_ai_menu(message: Message) -> None:
    await message.answer(JO_AI_MENU_TEXT, reply_markup=jo_ai_menu_keyboard())


def _feature_reply_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    return jo_chat_keyboard(back_callback)


def _chat_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joai:chat")


def _code_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joai:code")


def _research_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joai:research")


def _deep_analysis_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joai:deep_analysis")


def _prompt_type_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joai:menu")


def _prompt_details_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joaiprompt:type_menu")


def _image_prompt_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joaiimg:ratio_menu")


def _video_prompt_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joaivid:options_menu")


def _vision_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joai:kimi")


def _tts_text_reply_keyboard() -> InlineKeyboardMarkup:
    return _feature_reply_keyboard("joaitts:style_menu")


async def _send_step_message(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if bool(getattr(getattr(message, "from_user", None), "is_bot", False)):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
    await message.answer(text, reply_markup=reply_markup)


async def _send_chat_intro(message: Message) -> None:
    await message.answer(
        "<b>Step 1: JO AI Chat is active</b>\n\n"
        "Send your message and I will reply clearly.\n"
        "Use Back for AI tools, or Main Menu to leave this flow.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )


async def _send_gemini_intro(message: Message) -> None:
    if GEMINI_TEMP_DISABLED:
        await message.answer(
            "<b>Gemini mode is temporarily disabled</b>\n\n"
            "Image generation is being stabilized. Use /image for image requests.",
            reply_markup=jo_chat_keyboard("joai:menu"),
        )
        return
    await message.answer(
        "<b>Step 1: Gemini mode is active</b>\n\n"
        "Step 2: Choose Chat, Image, or Voice below.\n"
        "You can also type /image or /voice directly.",
        reply_markup=gemini_mode_keyboard(),
    )


def _gemini_mode_hint(mode: str) -> str:
    if mode == "image":
        return (
            "<b>Gemini image mode selected</b>\n\n"
            "Step 3: Send your prompt with <code>/image your prompt</code>.\n"
            "Example: <code>/image futuristic city skyline at sunset</code>"
        )
    if mode == "voice":
        return (
            "<b>Gemini voice mode selected</b>\n\n"
            "Step 3: Send text with <code>/voice your text</code>.\n"
            "Example: <code>/voice Welcome to JO AI Chat</code>"
        )
    return (
        "<b>Gemini chat mode selected</b>\n\n"
        "Step 3: Send a normal chat message, or use /image or /voice."
    )


async def _send_code_intro(message: Message) -> None:
    await message.answer(
        "<b>Step 1: Code Generator is active</b>\n\n"
        "Send a feature request, bug, or full build task.\n"
        "For debug/fix requests, upload the code file first.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )


async def _send_research_intro(message: Message) -> None:
    await message.answer(
        "<b>Step 1: Research mode is active</b>\n\n"
        "Send a topic or question and I'll return a clean breakdown with practical next steps.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )


async def _send_deep_analysis_intro(message: Message) -> None:
    await message.answer(
        "<b>Step 1: DeepSeek is active</b>\n\n"
        "Send your question and I'll slow down, compare tradeoffs, and reason through it carefully.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )


async def _send_prompt_type_step(message: Message) -> None:
    await _send_step_message(
        message,
        "<b>Prompt Generator is active</b>\n\n"
        "Step 1/2: Tell me the prompt type.\n"
        "Examples: ad copy, YouTube script, study guide, image prompt.",
        reply_markup=_prompt_type_reply_keyboard(),
    )


async def _send_prompt_details_step(message: Message) -> None:
    await _send_step_message(
        message,
        "Prompt type saved.\n\n"
        "Step 2/2: Describe what you want for that prompt type.\n"
        "Include audience, tone, goal, and constraints if possible.",
        reply_markup=_prompt_details_reply_keyboard(),
    )


async def _send_image_intro(message: Message) -> None:
    await _send_step_message(
        message,
        "<b>Image Generation is active</b>\n\n"
        "Step 1/2: Choose an image model.\n"
        "Options:\n"
        f"- {IMAGE_MODEL_LABELS[IMAGE_MODEL_OPTION_JO]}\n"
        f"- {IMAGE_MODEL_LABELS[IMAGE_MODEL_OPTION_CHAT_GBT]}\n"
        f"- {IMAGE_MODEL_LABELS[IMAGE_MODEL_OPTION_GROK_IMAGINE]}",
        reply_markup=image_model_keyboard(DEFAULT_IMAGE_MODEL_OPTION),
    )


async def _send_image_ratio_step(message: Message, model_label: str | None = None) -> None:
    intro = f"Model <b>{html.escape(model_label)}</b> selected.\n\n" if model_label else ""
    await _send_step_message(
        message,
        f"{intro}Step 2/2: Choose an aspect ratio.\n"
        "Available ratios: 1:1, 16:9, 9:16.\n\n"
        "After selecting a ratio, send your image prompt.",
        reply_markup=image_ratio_keyboard(),
    )


async def _send_image_prompt_step(message: Message, ratio_label: str, model_label: str) -> None:
    await _send_step_message(
        message,
        f"Model <b>{html.escape(model_label)}</b> with ratio <b>{html.escape(ratio_label)}</b> selected.\n\n"
        "Now send the image prompt.",
        reply_markup=_image_prompt_reply_keyboard(),
    )


async def _send_video_intro(
    message: Message,
    *,
    duration_seconds: int = DEFAULT_VIDEO_DURATION_SECONDS,
    aspect_ratio: str = DEFAULT_VIDEO_ASPECT_RATIO,
) -> None:
    await _send_step_message(
        message,
        "<b>Video Generation is active</b>\n\n"
        f"Mode: <b>{VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO}</b>\n"
        "Set duration and aspect ratio, then tap <b>Generate Video</b>.",
        reply_markup=video_options_keyboard(duration_seconds, aspect_ratio),
    )


async def _send_video_prompt_step(
    message: Message,
    *,
    duration_seconds: int,
    aspect_ratio: str,
) -> None:
    await _send_step_message(
        message,
        "Joined ✅\n\n"
        f"Duration <b>{duration_seconds}s</b> and ratio <b>{html.escape(aspect_ratio)}</b> selected.\n\n"
        "Send your video prompt now.",
        reply_markup=_video_prompt_reply_keyboard(),
    )


async def _send_video_join_required_step(message: Message) -> None:
    await _send_step_message(
        message,
        _video_join_required_text(),
        reply_markup=_video_join_required_keyboard(),
    )


async def _send_tts_language_step(message: Message) -> None:
    await _send_step_message(
        message,
        "<b>Text-to-Speech is active</b>\n\n"
        "Step 1/4: Choose a language.\n"
        "After male or female, you'll get several voice-style choices.\n"
        "Voice cloning is not supported in this release yet.",
        reply_markup=tts_language_keyboard(),
    )


async def _send_tts_voice_step(message: Message, language_label: str | None = None) -> None:
    intro = f"<b>{html.escape(language_label)}</b> selected.\n\n" if language_label else ""
    await _send_step_message(
        message,
        f"{intro}Step 2/4: Choose male or female.",
        reply_markup=tts_voice_keyboard(),
    )


async def _send_tts_style_step(message: Message, voice: str, voice_label: str | None = None) -> None:
    intro = f"Voice <b>{html.escape(voice_label)}</b> selected.\n\n" if voice_label else ""
    await _send_step_message(
        message,
        f"{intro}Step 3/4: Choose a voice style.",
        reply_markup=tts_style_keyboard(_tts_style_choices(voice)),
    )


async def _send_tts_text_step(message: Message, style_label: str) -> None:
    await _send_step_message(
        message,
        f"Style <b>{html.escape(style_label)}</b> selected.\n\n"
        "Step 4/4: Send the text you want me to convert to speech.",
        reply_markup=_tts_text_reply_keyboard(),
    )


async def _send_gpt_audio_intro(message: Message) -> None:
    await message.answer(
        "Send any question or prompt.\n"
        "I will generate an AI explanation in audio.\n"
        "Your text will be converted into a spoken response.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )


async def _send_vision_intro(message: Message) -> None:
    await message.answer(
        "<b>JO AI Vision is active</b>\n\n"
        "Send an image and I'll describe what I see.\n"
        "You can also include a short instruction with the photo.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )


def _uploaded_image_back_callback(session) -> str:
    if session.active_feature != Feature.JO_AI:
        return "menu:ai_tools"
    if session.jo_ai_mode == JoAIMode.CHAT:
        return "joai:chat"
    if session.jo_ai_mode == JoAIMode.CODE:
        return "joai:code"
    if session.jo_ai_mode == JoAIMode.RESEARCH:
        return "joai:research"
    if session.jo_ai_mode == JoAIMode.DEEP_ANALYSIS:
        return "joai:deep_analysis"
    if session.jo_ai_mode == JoAIMode.PROMPT:
        return "joaiprompt:type_menu" if session.jo_ai_prompt_type else "joai:prompt"
    if session.jo_ai_mode == JoAIMode.IMAGE:
        return "joaiimg:ratio_menu" if session.jo_ai_image_ratio else "joai:image"
    if session.jo_ai_mode == JoAIMode.VIDEO:
        return "joaivid:options_menu"
    if session.jo_ai_mode == JoAIMode.TEXT_TO_SPEECH:
        if session.jo_ai_tts_style:
            return "joaitts:style_menu"
        if session.jo_ai_tts_voice:
            return "joaitts:voice_menu"
        if session.jo_ai_tts_language:
            return "joaitts:lang_menu"
        return "joai:tts"
    if session.jo_ai_mode == JoAIMode.GPT_AUDIO:
        return "joai:gpt_audio"
    if session.jo_ai_mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
        return "joai:kimi"
    return "joai:menu"


async def _switch_to_jo_ai_mode(user_id: int, mode: JoAIMode, session_manager: SessionManager) -> None:
    async with session_manager.lock(user_id) as session:
        if session.active_feature == Feature.JO_AI:
            session.jo_ai_mode = mode
            if mode not in {JoAIMode.CHAT, JoAIMode.GEMINI}:
                session.jo_ai_chat_history.clear()
            if mode != JoAIMode.PROMPT:
                session.jo_ai_prompt_type = None
            if mode != JoAIMode.IMAGE:
                session.jo_ai_image_ratio = None
                session.jo_ai_image_model = None
            if mode != JoAIMode.VIDEO:
                session.jo_ai_video_duration = None
                session.jo_ai_video_aspect_ratio = None
            if mode != JoAIMode.KIMI_IMAGE_DESCRIBER:
                session.jo_ai_kimi_waiting_image = False
                session.jo_ai_last_image_prompt = None
            if mode != JoAIMode.CODE:
                session.jo_ai_code_waiting_file = False
                session.jo_ai_code_file_name = None
                session.jo_ai_code_file_content = None
            if mode != JoAIMode.TEXT_TO_SPEECH:
                session.jo_ai_tts_language = None
                session.jo_ai_tts_voice = None
                session.jo_ai_tts_style = None
                session.jo_ai_tts_emotion = None


async def _activate_mode(
    message: Message,
    user_id: int,
    mode: JoAIMode,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    transition = await session_manager.switch_feature(user_id, Feature.JO_AI)
    await _switch_to_jo_ai_mode(user_id, mode, session_manager)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))

    if mode == JoAIMode.CHAT:
        await _send_chat_intro(message)
        return
    if mode == JoAIMode.GEMINI:
        await _send_gemini_intro(message)
        return
    if mode == JoAIMode.CODE:
        await _send_code_intro(message)
        return
    if mode == JoAIMode.RESEARCH:
        await _send_research_intro(message)
        return
    if mode == JoAIMode.DEEP_ANALYSIS:
        await _send_deep_analysis_intro(message)
        return
    if mode == JoAIMode.PROMPT:
        await _send_prompt_type_step(message)
        return
    if mode == JoAIMode.IMAGE:
        async with session_manager.lock(user_id) as session:
            if not session.jo_ai_image_model:
                session.jo_ai_image_model = DEFAULT_IMAGE_MODEL_OPTION
        await _send_image_intro(message)
        return
    if mode == JoAIMode.VIDEO:
        if not await _is_video_generation_allowed(message.bot, user_id):
            await _send_video_join_required_step(message)
            return
        selected_duration = DEFAULT_VIDEO_DURATION_SECONDS
        selected_ratio = DEFAULT_VIDEO_ASPECT_RATIO
        async with session_manager.lock(user_id) as session:
            if session.jo_ai_video_duration in VIDEO_DURATION_OPTIONS:
                selected_duration = int(session.jo_ai_video_duration)
            else:
                session.jo_ai_video_duration = DEFAULT_VIDEO_DURATION_SECONDS
            if session.jo_ai_video_aspect_ratio in VIDEO_ASPECT_RATIO_OPTIONS:
                selected_ratio = str(session.jo_ai_video_aspect_ratio)
            else:
                session.jo_ai_video_aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO
        await _send_video_intro(
            message,
            duration_seconds=selected_duration,
            aspect_ratio=selected_ratio,
        )
        return
    if mode == JoAIMode.TEXT_TO_SPEECH:
        await _send_tts_language_step(message)
        return
    if mode == JoAIMode.GPT_AUDIO:
        await _send_gpt_audio_intro(message)
        return
    if mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
        await _send_vision_intro(message)
        return

    await message.answer("Select a JO AI mode to continue.", reply_markup=jo_ai_menu_keyboard())


async def _maybe_send_engagement(message: Message) -> None:
    _ = message
    return


def _is_kimi_unclear_result(error_text: str) -> bool:
    lower = error_text.lower()
    return "empty image description" in lower or "did not return image description choices" in lower


def _split_sentences(text: str, max_items: int = 5) -> list[str]:
    normalized = " ".join(text.replace("\r", "\n").split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
    lines = [part.strip() for part in parts if part.strip()]
    return lines[:max_items] if lines else [normalized]


def _clean_list_block(block: str, max_items: int = 6) -> list[str]:
    stripped_lines = [line.strip() for line in block.splitlines() if line.strip()]
    cleaned_lines: list[str] = []
    for line in stripped_lines:
        cleaned = re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    if cleaned_lines:
        return cleaned_lines[:max_items]

    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", block) if item.strip()]
    if len(paragraphs) > 1:
        return paragraphs[:max_items]
    return _split_sentences(block, max_items=max_items)


def _collect_named_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    labels = {
        "title": "title",
        "explanation": "explanation",
        "code language": "code language",
        "how to run": "how to run",
        "notes": "notes",
        "summary": "summary",
        "details": "details",
        "risks/tradeoffs": "risks/tradeoffs",
        "risks and tradeoffs": "risks/tradeoffs",
        "next steps": "next steps",
    }
    current_label: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_label
        if current_label is None:
            return
        payload = "\n".join(buffer).strip()
        if payload:
            sections[current_label] = _clean_list_block(payload, max_items=8)
        buffer = []
        current_label = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        match = re.match(
            r"^(Title|Explanation|Code Language|How to run|Notes|Summary|Details|Risks/Tradeoffs|Risks and Tradeoffs|Next Steps)\s*:\s*(.*)$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            flush()
            current_label = labels[match.group(1).lower()]
            inline_value = match.group(2).strip()
            if inline_value:
                buffer.append(inline_value)
            continue
        if current_label is not None:
            buffer.append(raw_line)
    flush()
    return sections


def _guess_code_language(code: str, fallback: str = "text") -> str:
    sample = code.strip().lower()
    if not sample:
        return fallback
    if sample.startswith("<!doctype html") or "<html" in sample:
        return "html"
    if sample.startswith("{") and '"name"' in sample:
        return "json"
    if "def " in sample or "import " in sample or "print(" in sample:
        return "python"
    if "console.log" in sample or "const " in sample or "function " in sample:
        return "javascript"
    if "public class " in sample:
        return "java"
    if "select " in sample or "insert into " in sample:
        return "sql"
    if "package main" in sample or "fmt." in sample:
        return "go"
    return fallback


def _default_run_steps(lang: str) -> list[str]:
    language = (lang or "text").lower()
    defaults = {
        "python": ["Save the file as output.py.", "Install dependencies if required.", "Run python output.py."],
        "javascript": ["Save the file as output.js.", "Install dependencies if required.", "Run node output.js."],
        "typescript": ["Save the file as output.ts.", "Install dependencies if required.", "Run it with your TypeScript toolchain."],
        "html": ["Save the file as output.html.", "Open the file in a browser.", "Use browser developer tools if you need to debug it."],
        "css": ["Save the file as output.css.", "Link it from your HTML file.", "Reload the page to verify the styles."],
        "sql": ["Open your SQL client.", "Paste the query into a new editor tab.", "Run it against the intended database."],
    }
    return defaults.get(language, ["Save the output to a file.", "Run it with the appropriate tool for this language."])


def _extract_code_body(reply_text: str) -> tuple[str, str]:
    fence_match = CODE_FENCE_PATTERN.search(reply_text)
    if fence_match:
        return fence_match.group("code").rstrip(), (fence_match.group("lang") or "").strip().lower()

    code_heading = re.search(r"(?im)^Code\s*:\s*$", reply_text)
    if not code_heading:
        return reply_text.strip(), ""

    trailing = reply_text[code_heading.end() :].strip()
    next_heading = re.search(
        r"(?im)^(How to run|Notes|Summary|Details|Risks/Tradeoffs|Risks and Tradeoffs|Next Steps)\s*:",
        trailing,
    )
    if next_heading:
        trailing = trailing[: next_heading.start()].strip()
    return trailing, ""


def _parse_code_reply(reply_text: str, fallback_title: str) -> ParsedCodeReply:
    code, fenced_lang = _extract_code_body(reply_text)
    text_without_code = CODE_FENCE_PATTERN.sub("", reply_text, count=1).strip()
    named_sections = _collect_named_sections(text_without_code)

    title = (named_sections.get("title") or [fallback_title])[0]
    explanation_lines = named_sections.get("explanation") or _clean_list_block(text_without_code, max_items=4)
    lang = fenced_lang or (named_sections.get("code language") or [""])[0].strip().lower()
    lang = _guess_code_language(code, fallback=lang or "text")
    run_steps = named_sections.get("how to run") or _default_run_steps(lang)
    notes_lines = named_sections.get("notes") or []

    if not explanation_lines:
        explanation_lines = [
            f"Generated a {lang} example tailored to your request.",
            "Review the configuration and dependencies before running it.",
        ]

    return ParsedCodeReply(
        title=title,
        explanation_lines=explanation_lines,
        code=code.strip(),
        lang=lang,
        run_steps=run_steps,
        notes_lines=notes_lines,
    )


def _friendly_error_text(title: str, exc: Exception | None = None) -> str:
    detail = ""
    if exc is not None:
        safe_detail = str(exc).strip()
        if safe_detail and safe_detail != SAFE_SERVICE_UNAVAILABLE_MESSAGE:
            detail = f"\nReason: {html.escape(safe_detail[:220])}"
    message = (
        f"Warning: <b>{title}</b>\n"
        f"{BRANDING_LINE}\n"
        "Please try again in a moment."
        f"{detail}\n"
        f"For JO API access, contact {DEVELOPER_HANDLE}."
    )
    if exc is not None:
        logger.warning("JO AI request failed.")
    return message


def _is_internal_rule_block(text: str | None) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized == SAFE_INTERNAL_DETAILS_REFUSAL:
        return True
    return "can't share internal backend or api details" in normalized.lower()


def _is_service_unavailable_error(exc: Exception | None) -> bool:
    if exc is None:
        return False
    normalized = str(exc).strip()
    if not normalized:
        return False
    return normalized == SAFE_SERVICE_UNAVAILABLE_MESSAGE


def _image_request_blocked_text() -> str:
    return (
        "Warning: <b>Image request blocked by rules.</b>\n"
        "This prompt asks for internal or backend details, so I did not send it to the image generator.\n"
        "Rewrite it as a visual description only and send it again."
    )


def _image_generation_failed_text(
    *,
    confirmed_unavailable: bool,
) -> str:
    title = "Image generation is unavailable right now." if confirmed_unavailable else "Image generation failed for this request."
    detail = "The image API is missing, inactive, or did not return a valid image."
    return f"Warning: <b>{title}</b>\n{detail}\nPlease retry in a moment."


def _compact_history_entry(text: str, limit: int = CHAT_HISTORY_ENTRY_MAX_CHARS) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}\n...[truncated for context]..."


def _is_code_debug_request(text: str) -> bool:
    return bool(DEBUG_INTENT_PATTERN.search(text or ""))


def _code_filename_for_language(lang: str) -> str:
    mapping = {
        "python": "output.py",
        "py": "output.py",
        "javascript": "output.js",
        "js": "output.js",
        "typescript": "output.ts",
        "ts": "output.ts",
        "cpp": "output.cpp",
        "c++": "output.cpp",
        "c": "output.c",
        "java": "Main.java",
        "go": "main.go",
        "html": "index.html",
        "css": "styles.css",
        "sql": "output.sql",
        "json": "output.json",
        "xml": "output.xml",
        "yaml": "output.yml",
        "yml": "output.yml",
        "bash": "script.sh",
        "sh": "script.sh",
        "php": "output.php",
        "rust": "main.rs",
    }
    key = (lang or "").strip().lower()
    return mapping.get(key, "output.txt")


def _file_is_code_like(file_name: str) -> bool:
    normalized = (file_name or "").lower()
    allowed_suffixes = (
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".cpp",
        ".cc",
        ".cxx",
        ".c",
        ".cs",
        ".go",
        ".rs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".m",
        ".mm",
        ".sql",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".sh",
        ".bat",
        ".ps1",
        ".txt",
        ".md",
        ".env",
    )
    return normalized.endswith(allowed_suffixes)


def _decode_uploaded_code_file(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = decoded.strip()
        if text:
            return text
    return None


def _build_code_debug_request(user_text: str, file_name: str, file_content: str) -> str:
    max_chars = 70_000
    normalized_code = file_content.strip()
    if len(normalized_code) > max_chars:
        normalized_code = normalized_code[:max_chars].rstrip() + "\n...[truncated for analysis]"
    return (
        f"Debug request:\n{user_text}\n\n"
        f"Target file: {file_name}\n\n"
        "Return the corrected version of this file as one complete file.\n"
        "Also include a short explanation of what was fixed.\n\n"
        f"```text\n{normalized_code}\n```"
    )


async def _send_code_generator_reply(
    message: Message,
    formatter: TelegramMessageFormatter,
    reply_text: str,
    reply_markup,
) -> None:
    normalized_reply = reply_text.strip() or "No output generated."
    parsed = _parse_code_reply(normalized_reply, MODE_RESULT_TITLE["code"])
    code_body = parsed.code.strip() or normalized_reply
    code_lang = parsed.lang or _guess_code_language(code_body, fallback="text")
    file_name = _code_filename_for_language(code_lang)
    attach_full_file = len(code_body) >= LONG_CODE_ATTACHMENT_THRESHOLD or len(normalized_reply) >= MAX_REPLY_CHARS
    is_extremely_long = len(code_body) >= EXTREME_CODE_LENGTH_THRESHOLD

    if is_extremely_long:
        summary_lines = parsed.explanation_lines or _clean_list_block(normalized_reply, max_items=4)
        starter_snippet = code_body[:900].rstrip()
        summary_text = "Full code is attached as one file.\n\nSummary:\n" + "\n".join(
            f"- {line}" for line in summary_lines[:6]
        )
        if starter_snippet:
            summary_text += f"\n\nStarter snippet:\n```{code_lang}\n{starter_snippet}\n```"
        await formatter.send_paginated_text_response(
            chat_id=message.chat.id,
            title="Code Result",
            body_text=summary_text,
            reply_markup=reply_markup,
        )
    else:
        await formatter.send_rich_response(
            chat_id=message.chat.id,
            title="Code Result",
            raw_text=normalized_reply,
            reply_markup=reply_markup,
        )

    if attach_full_file:
        code_file = BufferedInputFile(code_body.encode("utf-8"), filename=file_name)
        await message.bot.send_document(
            chat_id=message.chat.id,
            document=code_file,
            caption=f"Full code file attached: {file_name}",
        )


async def _send_progress_message(message: Message, text: str) -> Message | None:
    try:
        return await message.answer(text)
    except Exception:
        return None


async def _clear_progress_message(progress_message: Message | None) -> None:
    if progress_message is None:
        return
    with suppress(TelegramBadRequest):
        await progress_message.delete()


async def _send_styled_ai_reply(
    message: Message,
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    reply_text: str,
    reply_markup,
) -> None:
    await _send_formatted_ai_reply(message, mode, reply_text, reply_markup)


async def _send_formatted_ai_reply(
    message: Message,
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    reply_text: str,
    reply_markup,
) -> None:
    formatter = TelegramMessageFormatter(message.bot)
    normalized_reply = reply_text.strip() or "No output generated."
    title = MODE_RESULT_TITLE.get(mode, "AI Result")

    if mode == "code":
        await _send_code_generator_reply(message, formatter, normalized_reply, reply_markup)
        return

    if CODE_FENCE_PATTERN.search(normalized_reply):
        await formatter.send_rich_response(chat_id=message.chat.id, title=title, raw_text=normalized_reply, reply_markup=reply_markup)
        return

    await formatter.send_paginated_text_response(
        chat_id=message.chat.id,
        title=title,
        body_text=normalized_reply,
        reply_markup=reply_markup,
    )


@router.message(Command("joai"))
@router.message(Command("chat"))
@router.message(Command("code"))
@router.message(Command("research"))
@router.message(Command("prompt"))
@router.message(Command("image"))
@router.message(Command("video"))
@router.message(Command("deepseek"))
@router.message(Command("analysis"))
@router.message(Command("gemini"))
@router.message(Command("kimi"))
@router.message(Command("vision"))
@router.message(Command("tts"))
@router.message(Command("gptaudio"))
@router.message(F.text == MENU_AI_CHAT)
@router.message(F.text == "JO AI Chat")
@router.message(F.text == MENU_AI_CODE)
@router.message(F.text == "Code Generator")
@router.message(F.text == MENU_AI_RESEARCH)
@router.message(F.text == "Research")
@router.message(F.text == MENU_AI_PROMPT)
@router.message(F.text == "Prompt Generator")
@router.message(F.text == MENU_AI_IMAGE)
@router.message(F.text == "Image Generator")
@router.message(F.text == MENU_AI_VIDEO)
@router.message(F.text == "Video Generation")
@router.message(F.text == MENU_AI_DEEPSEEK)
@router.message(F.text == MENU_AI_GEMINI)
@router.message(F.text == MENU_AI_KIMI)
@router.message(F.text == MENU_AI_TTS)
@router.message(F.text == "Text-to-Speech")
@router.message(F.text == MENU_AI_GPT_AUDIO)
@router.message(F.text == "GPT Audio")
@router.message(F.text == MENU_AI_TOOLS)
@router.message(F.text == "AI Tools")
@router.message(F.text == MENU_JO_AI)
@router.message(F.text == "Jo AI")
async def open_jo_ai_menu(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    text = (message.text or "").strip().lower()
    if text in {"/chat", MENU_AI_CHAT.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.CHAT, session_manager, miniapp_url)
        return
    if text in {"/gemini", MENU_AI_GEMINI.lower()}:
        if GEMINI_TEMP_DISABLED:
            await message.answer(
                "Gemini mode is temporarily disabled while image generation is being stabilized.",
                reply_markup=jo_ai_menu_keyboard(),
            )
            return
        await _activate_mode(message, message.from_user.id, JoAIMode.GEMINI, session_manager, miniapp_url)
        return
    if text in {"/code", MENU_AI_CODE.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.CODE, session_manager, miniapp_url)
        return
    if text in {"/research", MENU_AI_RESEARCH.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.RESEARCH, session_manager, miniapp_url)
        return
    if text in {"/prompt", MENU_AI_PROMPT.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.PROMPT, session_manager, miniapp_url)
        return
    if text in {"/image", MENU_AI_IMAGE.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.IMAGE, session_manager, miniapp_url)
        return
    if text in {"/video", MENU_AI_VIDEO.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.VIDEO, session_manager, miniapp_url)
        return
    if text in {"/kimi", "/vision", MENU_AI_KIMI.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.KIMI_IMAGE_DESCRIBER, session_manager, miniapp_url)
        return
    if text in {"/tts", MENU_AI_TTS.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.TEXT_TO_SPEECH, session_manager, miniapp_url)
        return
    if text in {"/gptaudio", MENU_AI_GPT_AUDIO.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.GPT_AUDIO, session_manager, miniapp_url)
        return
    if text in {"/deepseek", "/analysis", MENU_AI_DEEPSEEK.lower()}:
        await _activate_mode(message, message.from_user.id, JoAIMode.DEEP_ANALYSIS, session_manager, miniapp_url)
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.AI_TOOLS_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await _show_jo_ai_menu(message)


@router.message(Command("exit_chat"))
async def exit_chat_command(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return
    transition = await session_manager.switch_feature(message.from_user.id, Feature.AI_TOOLS_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer("Exited current mode. Returning to AI tools menu.")
    await _show_jo_ai_menu(message)


@router.callback_query(F.data == "joai:menu")
async def open_jo_ai_submenu_callback(
    query: CallbackQuery,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return
    transition = await session_manager.switch_feature(query.from_user.id, Feature.AI_TOOLS_MENU)
    await query.answer()
    if isinstance(query.message, Message):
        if transition.notice:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await _show_jo_ai_menu(query.message)


@router.callback_query(F.data == "joai:chat")
async def enable_jo_chat(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.CHAT, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:gemini")
async def enable_gemini_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    if GEMINI_TEMP_DISABLED:
        await query.answer("Gemini is temporarily disabled.", show_alert=True)
        if isinstance(query.message, Message):
            await query.message.answer(
                "Gemini mode is temporarily disabled while image generation is being stabilized.",
                reply_markup=jo_ai_menu_keyboard(),
            )
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.GEMINI, session_manager, miniapp_url)


@router.callback_query(F.data.startswith("joaigem:mode:"))
async def select_gemini_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    if GEMINI_TEMP_DISABLED:
        await query.answer("Gemini is temporarily disabled.", show_alert=True)
        return

    mode_token = str(query.data or "").split(":")[-1].strip().lower()
    if mode_token not in {"chat", "image", "voice"}:
        await query.answer()
        return

    transition = await session_manager.switch_feature(query.from_user.id, Feature.JO_AI)
    await _switch_to_jo_ai_mode(query.from_user.id, JoAIMode.GEMINI, session_manager)
    await query.answer(f"Gemini {mode_token} selected")

    if isinstance(query.message, Message):
        if transition.notice:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await query.message.answer(
            _gemini_mode_hint(mode_token),
            reply_markup=gemini_mode_keyboard(),
        )


@router.callback_query(F.data == "joai:code")
async def enable_code_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.CODE, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:research")
async def enable_research_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.RESEARCH, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:deep_analysis")
async def enable_deep_analysis_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.DEEP_ANALYSIS, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:prompt")
async def enable_prompt_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.PROMPT, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:image")
async def enable_image_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.IMAGE, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:video")
async def enable_video_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.VIDEO, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:kimi")
async def enable_kimi_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.KIMI_IMAGE_DESCRIBER, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:tts")
async def enable_tts_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.TEXT_TO_SPEECH, session_manager, miniapp_url)


@router.callback_query(F.data == "joai:gpt_audio")
async def enable_gpt_audio_mode(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await _activate_mode(query.message, query.from_user.id, JoAIMode.GPT_AUDIO, session_manager, miniapp_url)


@router.callback_query(F.data == "joaitts:lang_menu")
async def tts_show_language_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.TEXT_TO_SPEECH:
            await query.answer("TTS session expired. Send /tts again.", show_alert=True)
            return
        session.jo_ai_tts_language = None
        session.jo_ai_tts_voice = None
        session.jo_ai_tts_style = None
        session.jo_ai_tts_emotion = None

    await query.answer()
    if isinstance(query.message, Message):
        await _send_tts_language_step(query.message)


@router.callback_query(F.data == "joaitts:voice_menu")
async def tts_show_voice_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    language_label: str | None = None
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.TEXT_TO_SPEECH:
            await query.answer("TTS session expired. Send /tts again.", show_alert=True)
            return
        if not session.jo_ai_tts_language:
            await query.answer("Pick a language first.", show_alert=True)
            return
        language_label = TTS_LANGUAGE_LABELS.get(session.jo_ai_tts_language, session.jo_ai_tts_language)
        session.jo_ai_tts_voice = None
        session.jo_ai_tts_style = None
        session.jo_ai_tts_emotion = None

    await query.answer()
    if isinstance(query.message, Message):
        await _send_tts_voice_step(query.message, language_label)


@router.callback_query(F.data.startswith("joaitts:lang:"))
async def choose_tts_language(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid language option.", show_alert=True)
        return
    language = parts[2].strip().lower()
    label = TTS_LANGUAGE_LABELS.get(language)
    if not label:
        await query.answer("Unsupported language.", show_alert=True)
        return

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.TEXT_TO_SPEECH:
            await query.answer("TTS session expired. Send /tts again.", show_alert=True)
            return
        session.jo_ai_tts_language = language
        session.jo_ai_tts_voice = None
        session.jo_ai_tts_style = None
        session.jo_ai_tts_emotion = None

    await query.answer(f"{label} selected.")
    if isinstance(query.message, Message):
        await _send_tts_voice_step(query.message, label)


@router.callback_query(F.data == "joaitts:clone")
async def tts_clone_unavailable(query: CallbackQuery) -> None:
    await query.answer("Voice cloning is not supported in this release yet.", show_alert=True)


@router.callback_query(F.data == "joaitts:style_menu")
async def tts_show_style_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    voice: str | None = None
    voice_label: str | None = None
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.TEXT_TO_SPEECH:
            await query.answer("TTS session expired. Send /tts again.", show_alert=True)
            return
        if not session.jo_ai_tts_language or not session.jo_ai_tts_voice:
            await query.answer("Select language and voice first.", show_alert=True)
            return
        session.jo_ai_tts_style = None
        session.jo_ai_tts_emotion = None
        voice = session.jo_ai_tts_voice
        voice_label = TTS_VOICE_LABELS.get(voice, voice)

    await query.answer()
    if isinstance(query.message, Message) and voice:
        await _send_tts_style_step(query.message, voice, voice_label)


@router.callback_query(F.data.startswith("joaitts:voice:"))
async def choose_tts_voice(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid voice option.", show_alert=True)
        return
    voice = parts[2].strip().lower()
    label = TTS_VOICE_LABELS.get(voice)
    if not label:
        await query.answer("Unsupported voice option.", show_alert=True)
        return

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.TEXT_TO_SPEECH:
            await query.answer("TTS session expired. Send /tts again.", show_alert=True)
            return
        if not session.jo_ai_tts_language:
            await query.answer("Pick a language first.", show_alert=True)
            return
        session.jo_ai_tts_voice = voice
        session.jo_ai_tts_style = None
        session.jo_ai_tts_emotion = None

    await query.answer(f"{label} selected.")
    if isinstance(query.message, Message):
        await _send_tts_style_step(query.message, voice, label)


@router.callback_query(F.data.startswith("joaitts:style:"))
async def choose_tts_style(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid style option.", show_alert=True)
        return
    style = parts[2].strip().lower()

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.TEXT_TO_SPEECH:
            await query.answer("TTS session expired. Send /tts again.", show_alert=True)
            return
        if not session.jo_ai_tts_language or not session.jo_ai_tts_voice:
            await query.answer("Select language and voice first.", show_alert=True)
            return
        label = _tts_style_label(session.jo_ai_tts_voice, style)
        emotion = _tts_style_emotion(session.jo_ai_tts_voice, style)
        if not emotion:
            await query.answer("Unsupported style option.", show_alert=True)
            return
        session.jo_ai_tts_style = style
        session.jo_ai_tts_emotion = emotion

    await query.answer(f"{label} style selected.")
    if isinstance(query.message, Message):
        await _send_tts_text_step(query.message, label)


@router.callback_query(F.data == "joaiprompt:type_menu")
async def prompt_show_type_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.PROMPT:
            await query.answer("Prompt session expired. Send /prompt again.", show_alert=True)
            return
        session.jo_ai_prompt_type = None

    await query.answer()
    if isinstance(query.message, Message):
        await _send_prompt_type_step(query.message)


@router.callback_query(F.data == "joaiimg:ratio_menu")
async def image_show_ratio_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    model_label: str = IMAGE_MODEL_LABELS[DEFAULT_IMAGE_MODEL_OPTION]
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("Image session expired. Send /image again.", show_alert=True)
            return
        session.jo_ai_image_ratio = None
        session.jo_ai_image_model = _resolve_image_model_option(session.jo_ai_image_model)
        model_label = _image_model_label(session.jo_ai_image_model)

    await query.answer()
    if isinstance(query.message, Message):
        await _send_image_ratio_step(query.message, model_label)


@router.callback_query(F.data == "joaiimg:model_menu")
async def image_show_model_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    selected_model = DEFAULT_IMAGE_MODEL_OPTION
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("Image session expired. Send /image again.", show_alert=True)
            return
        selected_model = _resolve_image_model_option(session.jo_ai_image_model)
        session.jo_ai_image_model = selected_model

    await query.answer()
    if isinstance(query.message, Message):
        await _send_step_message(
            query.message,
            "<b>Select an image model</b>\n\n"
            "Choose one option below. Provider internals stay hidden.",
            reply_markup=image_model_keyboard(selected_model),
        )


@router.callback_query(F.data.startswith("joaiimg:model:"))
async def choose_image_model(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid model option.", show_alert=True)
        return
    model_option = _resolve_image_model_option(parts[2].strip())
    model_label = _image_model_label(model_option)

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("Image session expired. Send /image again.", show_alert=True)
            return
        session.jo_ai_image_model = model_option

    await query.answer(f"{model_label} selected.")
    if isinstance(query.message, Message):
        await _send_image_ratio_step(query.message, model_label)


@router.callback_query(F.data.startswith("joaiimg:ratio:"))
async def choose_image_ratio(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid ratio option.", show_alert=True)
        return
    ratio = IMAGE_RATIO_TOKEN_MAP.get(parts[2])
    if not ratio:
        await query.answer("Unsupported ratio.", show_alert=True)
        return

    model_label = IMAGE_MODEL_LABELS[DEFAULT_IMAGE_MODEL_OPTION]
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.IMAGE:
            await query.answer("Image session expired. Send /image again.", show_alert=True)
            return
        session.jo_ai_image_ratio = ratio
        session.jo_ai_image_model = _resolve_image_model_option(session.jo_ai_image_model)
        model_label = _image_model_label(session.jo_ai_image_model)

    await query.answer(f"Ratio {ratio} selected.")
    if isinstance(query.message, Message):
        await _send_image_prompt_step(query.message, ratio, model_label)


@router.callback_query(F.data == "joaivid:options_menu")
async def video_show_options_menu(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    duration_seconds = DEFAULT_VIDEO_DURATION_SECONDS
    aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.VIDEO:
            await query.answer("Video session expired. Send /video again.", show_alert=True)
            return
        if session.jo_ai_video_duration in VIDEO_DURATION_OPTIONS:
            duration_seconds = int(session.jo_ai_video_duration)
        else:
            session.jo_ai_video_duration = DEFAULT_VIDEO_DURATION_SECONDS
        if session.jo_ai_video_aspect_ratio in VIDEO_ASPECT_RATIO_OPTIONS:
            aspect_ratio = str(session.jo_ai_video_aspect_ratio)
        else:
            session.jo_ai_video_aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO

    bot_instance = query.message.bot if isinstance(query.message, Message) else query.bot
    if not await _is_video_generation_allowed(bot_instance, query.from_user.id):
        await query.answer("Join the channel to unlock video generation.", show_alert=True)
        if isinstance(query.message, Message):
            await _send_video_join_required_step(query.message)
        return

    await query.answer()
    if isinstance(query.message, Message):
        await _send_video_intro(
            query.message,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )


@router.callback_query(F.data.startswith("joaivid:duration:"))
async def choose_video_duration(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid duration option.", show_alert=True)
        return
    try:
        duration_seconds = int(parts[2].strip())
    except ValueError:
        await query.answer("Invalid duration option.", show_alert=True)
        return
    if duration_seconds not in VIDEO_DURATION_OPTIONS:
        await query.answer("Unsupported duration.", show_alert=True)
        return

    aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.VIDEO:
            await query.answer("Video session expired. Send /video again.", show_alert=True)
            return
        session.jo_ai_video_duration = duration_seconds
        if session.jo_ai_video_aspect_ratio in VIDEO_ASPECT_RATIO_OPTIONS:
            aspect_ratio = str(session.jo_ai_video_aspect_ratio)
        else:
            session.jo_ai_video_aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO

    await query.answer(f"Duration {duration_seconds}s selected.")
    if isinstance(query.message, Message):
        await _send_video_intro(
            query.message,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )


@router.callback_query(F.data.startswith("joaivid:ratio:"))
async def choose_video_ratio(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) != 3:
        await query.answer("Invalid ratio option.", show_alert=True)
        return
    ratio = VIDEO_ASPECT_RATIO_TOKEN_MAP.get(parts[2].strip())
    if ratio not in VIDEO_ASPECT_RATIO_OPTIONS:
        await query.answer("Unsupported ratio.", show_alert=True)
        return

    duration_seconds = DEFAULT_VIDEO_DURATION_SECONDS
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.VIDEO:
            await query.answer("Video session expired. Send /video again.", show_alert=True)
            return
        session.jo_ai_video_aspect_ratio = ratio
        if session.jo_ai_video_duration in VIDEO_DURATION_OPTIONS:
            duration_seconds = int(session.jo_ai_video_duration)
        else:
            session.jo_ai_video_duration = DEFAULT_VIDEO_DURATION_SECONDS

    await query.answer(f"Ratio {ratio} selected.")
    if isinstance(query.message, Message):
        await _send_video_intro(
            query.message,
            duration_seconds=duration_seconds,
            aspect_ratio=ratio,
        )


@router.callback_query(F.data == "joaivid:generate")
async def prepare_video_generation(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return

    duration_seconds = DEFAULT_VIDEO_DURATION_SECONDS
    aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.VIDEO:
            await query.answer("Video session expired. Send /video again.", show_alert=True)
            return
        if session.jo_ai_video_duration in VIDEO_DURATION_OPTIONS:
            duration_seconds = int(session.jo_ai_video_duration)
        else:
            session.jo_ai_video_duration = DEFAULT_VIDEO_DURATION_SECONDS
        if session.jo_ai_video_aspect_ratio in VIDEO_ASPECT_RATIO_OPTIONS:
            aspect_ratio = str(session.jo_ai_video_aspect_ratio)
        else:
            session.jo_ai_video_aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO

    bot_instance = query.message.bot if isinstance(query.message, Message) else query.bot
    if not await _is_video_generation_allowed(bot_instance, query.from_user.id):
        await query.answer("Join required before generation.", show_alert=True)
        if isinstance(query.message, Message):
            await _send_video_join_required_step(query.message)
        return

    await query.answer("Joined ✅")
    if isinstance(query.message, Message):
        await _send_video_prompt_step(
            query.message,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )


@router.callback_query(F.data == "joaivid:joined_check")
async def check_video_join_after_button(query: CallbackQuery, session_manager: SessionManager) -> None:
    if not query.from_user:
        await query.answer()
        return

    duration_seconds = DEFAULT_VIDEO_DURATION_SECONDS
    aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO
    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.VIDEO:
            await query.answer("Video session expired. Send /video again.", show_alert=True)
            return
        if session.jo_ai_video_duration in VIDEO_DURATION_OPTIONS:
            duration_seconds = int(session.jo_ai_video_duration)
        else:
            session.jo_ai_video_duration = DEFAULT_VIDEO_DURATION_SECONDS
        if session.jo_ai_video_aspect_ratio in VIDEO_ASPECT_RATIO_OPTIONS:
            aspect_ratio = str(session.jo_ai_video_aspect_ratio)
        else:
            session.jo_ai_video_aspect_ratio = DEFAULT_VIDEO_ASPECT_RATIO

    bot_instance = query.message.bot if isinstance(query.message, Message) else query.bot
    if not await _is_video_generation_allowed(bot_instance, query.from_user.id):
        await query.answer("Still not joined. Please join then tap Joined ✅.", show_alert=True)
        if isinstance(query.message, Message):
            await _send_video_join_required_step(query.message)
        return

    await query.answer("Joined ✅")
    if isinstance(query.message, Message):
        await _send_video_prompt_step(
            query.message,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )


@router.callback_query(F.data.startswith("joai:"))
async def handle_jo_ai_action(query: CallbackQuery) -> None:
    if not query.from_user:
        await query.answer()
        return
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(
            "Unknown AI action.\nPlease use the buttons below.",
            reply_markup=jo_ai_menu_keyboard(),
        )


@router.message(
    ActiveFeatureFilter(Feature.JO_AI),
    F.text,
    ~F.text.in_(MENU_BUTTON_TEXTS),
    ~F.text.startswith("/"),
)
async def handle_jo_ai_text(
    message: Message,
    session_manager: SessionManager,
    chat_service: ChatService,
    gemini_service: GeminiChatService,
    image_generation_service: ImageGenerationService,
    pollinations_media_service: PollinationsMediaService,
    tts_service: TextToSpeechService,
    deepseek_api_key: str | None,
    deepseek_model: str,
    tracking_service: SupabaseTrackingService | None = None,
) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text:
        reply_text = "Please send a text message to continue."
        await message.answer(reply_text)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="chat",
            user_message="",
            bot_reply=reply_text,
            model_used=None,
            success=False,
            message_increment=1,
        )
        return

    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU
        prompt_type = session.jo_ai_prompt_type
        image_ratio = session.jo_ai_image_ratio
        image_model = session.jo_ai_image_model
        video_duration = session.jo_ai_video_duration
        video_aspect_ratio = session.jo_ai_video_aspect_ratio
        code_file_name = session.jo_ai_code_file_name
        code_file_content = session.jo_ai_code_file_content
        tts_language = session.jo_ai_tts_language
        tts_voice = session.jo_ai_tts_voice
        tts_style = session.jo_ai_tts_style
        tts_emotion = session.jo_ai_tts_emotion
        history_snapshot = [{"role": role, "content": content} for role, content in session.jo_ai_chat_history]

    mode_options = _default_mode_options()
    user_text = text

    if mode == JoAIMode.CHAT:
        await _process_chat_message(
            message,
            user_text,
            session_manager,
            chat_service,
            history_snapshot,
            "chat",
            mode_options,
            reply_markup=_chat_reply_keyboard(),
            tracking_service=tracking_service,
            tracking_message_type="chat",
            tracking_user_message=text,
        )
        return

    if mode == JoAIMode.GEMINI:
        await _process_gemini_message(
            message=message,
            user_text=user_text,
            session_manager=session_manager,
            gemini_service=gemini_service,
            image_generation_service=image_generation_service,
            tts_service=tts_service,
            tracking_service=tracking_service,
        )
        return

    if mode == JoAIMode.CODE:
        debug_request = _is_code_debug_request(text)
        if debug_request and not code_file_content:
            async with session_manager.lock(message.from_user.id) as session:
                session.jo_ai_code_waiting_file = True
            reply_text = (
                "To debug or fix code, upload the file first in Code Generator mode.\n"
                "Then send your debug request."
            )
            await message.answer(reply_text, reply_markup=_code_reply_keyboard())
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="code",
                user_message=text,
                bot_reply=reply_text,
                model_used=_chat_model_used(chat_service, mode_options),
                success=False,
                message_increment=1,
            )
            return

        if debug_request and code_file_content:
            user_text = _build_code_debug_request(text, code_file_name or "uploaded_code.txt", code_file_content)
        elif code_file_content and text.lower() in {"analyze file", "analyze", "review file"}:
            user_text = (
                f"Analyze this uploaded code file and suggest fixes.\n"
                f"Target file: {code_file_name or 'uploaded_code.txt'}\n\n"
                f"```text\n{code_file_content}\n```"
            )

        await _process_chat_message(
            message,
            user_text,
            session_manager,
            chat_service,
            [],
            "code",
            mode_options,
            reply_markup=_code_reply_keyboard(),
            tracking_service=tracking_service,
            tracking_message_type="code",
            tracking_user_message=text,
        )
        return

    if mode == JoAIMode.RESEARCH:
        await _process_chat_message(
            message,
            user_text,
            session_manager,
            chat_service,
            [],
            "research",
            mode_options,
            reply_markup=_research_reply_keyboard(),
            tracking_service=tracking_service,
            tracking_message_type="research",
            tracking_user_message=text,
        )
        return
    if mode == JoAIMode.DEEP_ANALYSIS:
        mode_options = _deep_analysis_mode_options(deepseek_api_key, deepseek_model)
        mode_prefix = str(mode_options.get("mode_prefix", "")).strip()
        deep_text = f"{mode_prefix}\n\n{text}" if mode_prefix else text
        await _process_chat_message(
            message,
            deep_text,
            session_manager,
            chat_service,
            [],
            "research",
            mode_options,
            reply_markup=_deep_analysis_reply_keyboard(),
            tracking_service=tracking_service,
            tracking_message_type="deep_analysis",
            tracking_user_message=text,
        )
        return

    if mode == JoAIMode.PROMPT:
        await _process_prompt_message(
            message,
            user_text,
            session_manager,
            chat_service,
            prompt_type,
            mode_options,
            tracking_service,
        )
        return
    if mode == JoAIMode.IMAGE:
        await _process_image_message(
            message,
            user_text,
            session_manager,
            image_generation_service,
            pollinations_media_service,
            image_ratio,
            image_model,
            tracking_service,
        )
        return
    if mode == JoAIMode.VIDEO:
        await _process_video_message(
            message,
            user_text,
            pollinations_media_service,
            video_duration,
            video_aspect_ratio,
            tracking_service,
        )
        return
    if mode == JoAIMode.TEXT_TO_SPEECH:
        await _process_tts_message(
            message,
            user_text,
            tts_service,
            tts_language,
            tts_voice,
            tts_style,
            tts_emotion,
            tracking_service,
        )
        return
    if mode == JoAIMode.GPT_AUDIO:
        await _process_gpt_audio_message(
            message,
            user_text,
            pollinations_media_service,
            tracking_service,
        )
        return
    if mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
        reply_text = "Send an image and I will describe it.\nYou can also include a short instruction."
        await message.answer(reply_text, reply_markup=_vision_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="vision",
            user_message=text,
            bot_reply=reply_text,
            model_used=None,
            success=True,
            message_increment=1,
        )
        return

    fallback_reply = "Pick an AI mode first from the menu below."
    await message.answer(fallback_reply, reply_markup=jo_ai_menu_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="menu",
        user_message=text,
        bot_reply=fallback_reply,
        model_used=None,
        success=False,
        message_increment=1,
    )


@router.message(F.document)
async def handle_code_document_upload(
    message: Message,
    session_manager: SessionManager,
    chat_service: ChatService,
    tracking_service: SupabaseTrackingService | None = None,
) -> None:
    if not message.from_user or not message.document:
        return

    document = message.document
    mime_type = (document.mime_type or "").strip().lower()
    if mime_type.startswith("image/"):
        await _prompt_uploaded_image_action(
            message,
            session_manager,
            document.file_id,
            (message.caption or "").strip(),
        )
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="vision",
            user_message=_tracking_text_from_message(message, "[image document]"),
            bot_reply="Image upload received. Waiting for describe confirmation.",
            model_used=None,
            success=True,
            message_increment=1,
            feature_used="image_vision",
            media=TrackingMedia(
                media_type="image",
                storage_path=f"telegram_file:{document.file_id}",
                mime_type=(document.mime_type or "").strip() or None,
                provider_source="telegram",
                media_origin="upload",
                media_status="available",
            ),
        )
        return

    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU

    if mode != JoAIMode.CODE:
        reply_text = "File upload analysis is available only in <b>Code Generator</b> mode."
        await message.answer(reply_text, reply_markup=jo_chat_keyboard("joai:menu"))
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="code",
            user_message=_tracking_text_from_message(message, "[document]"),
            bot_reply=reply_text,
            model_used=None,
            success=False,
            message_increment=1,
        )
        return

    file_name = document.file_name or "uploaded_code.txt"
    file_size = int(document.file_size or 0)
    if file_size > MAX_CODE_UPLOAD_BYTES:
        reply_text = "File is too large for code analysis here.\nPlease upload a file smaller than 1.5MB."
        await message.answer(reply_text, reply_markup=_code_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="code",
            user_message=_tracking_text_from_message(message, f"[document:{file_name}]"),
            bot_reply=reply_text,
            model_used=None,
            success=False,
            message_increment=1,
        )
        return
    if not _file_is_code_like(file_name):
        reply_text = "Please upload a source-code or text file for debugging."
        await message.answer(reply_text, reply_markup=_code_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="code",
            user_message=_tracking_text_from_message(message, f"[document:{file_name}]"),
            bot_reply=reply_text,
            model_used=None,
            success=False,
            message_increment=1,
        )
        return

    progress_message = await _send_progress_message(message, "Reading uploaded code file...")
    try:
        file = await message.bot.get_file(document.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        raw_bytes = downloaded.read()
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Failed to download uploaded code file.")
        reply_text = "I could not read that file. Please upload it again."
        await message.answer(reply_text)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="code",
            user_message=_tracking_text_from_message(message, f"[document:{file_name}]"),
            bot_reply=reply_text,
            model_used=None,
            success=False,
            message_increment=1,
        )
        return

    decoded = _decode_uploaded_code_file(raw_bytes)
    if not decoded:
        await _clear_progress_message(progress_message)
        reply_text = "I couldn't decode that file as text code.\nUpload a plain text source file."
        await message.answer(reply_text, reply_markup=_code_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="code",
            user_message=_tracking_text_from_message(message, f"[document:{file_name}]"),
            bot_reply=reply_text,
            model_used=None,
            success=False,
            message_increment=1,
        )
        return

    async with session_manager.lock(message.from_user.id) as session:
        if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.CODE:
            await _clear_progress_message(progress_message)
            reply_text = "Code session expired. Send /code and try again."
            await message.answer(reply_text)
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="code",
                user_message=_tracking_text_from_message(message, f"[document:{file_name}]"),
                bot_reply=reply_text,
                model_used=None,
                success=False,
                message_increment=1,
            )
            return
        session.jo_ai_code_file_name = file_name
        session.jo_ai_code_file_content = decoded
        session.jo_ai_code_waiting_file = False

    await _clear_progress_message(progress_message)
    caption_text = (message.caption or "").strip()
    if caption_text:
        mode_options = _default_mode_options()
        if _is_code_debug_request(caption_text):
            user_text = _build_code_debug_request(caption_text, file_name, decoded)
        else:
            user_text = (
                f"Use this uploaded file as the main context.\n"
                f"File: {file_name}\n"
                f"User request: {caption_text}\n\n"
                f"```text\n{decoded}\n```"
            )
        await _process_chat_message(
            message,
            user_text,
            session_manager,
            chat_service,
            [],
            "code",
            mode_options,
            tracking_service=tracking_service,
            tracking_message_type="code",
            tracking_user_message=caption_text,
        )
        return

    reply_text = f"File received: <b>{html.escape(file_name)}</b>\nNow send what you want me to debug or fix."
    await message.answer(reply_text, reply_markup=_code_reply_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="code",
        user_message=_tracking_text_from_message(message, f"[document:{file_name}]"),
        bot_reply=reply_text,
        model_used=None,
        success=True,
        message_increment=1,
    )


async def _prompt_uploaded_image_action(
    message: Message,
    session_manager: SessionManager,
    file_id: str,
    prompt_text: str | None = None,
) -> None:
    cleaned_prompt = (prompt_text or "").strip() or None
    back_callback = "menu:ai_tools"
    async with session_manager.lock(message.from_user.id) as session:
        session.jo_ai_last_image_file_id = file_id
        session.jo_ai_last_image_prompt = cleaned_prompt
        back_callback = _uploaded_image_back_callback(session)

    await message.answer(
        "You uploaded an image. Do you want me to describe it?",
        reply_markup=uploaded_image_keyboard(back_callback),
    )


@router.message(F.photo)
async def handle_kimi_photo(
    message: Message,
    session_manager: SessionManager,
    chat_service: ChatService,
    kimi_api_key: str | None,
    kimi_model: str,
    tracking_service: SupabaseTrackingService | None = None,
) -> None:
    if not message.from_user or not message.photo:
        return

    largest = message.photo[-1]
    prompt_text = (message.caption or "").strip()
    async with session_manager.lock(message.from_user.id) as session:
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU
        if mode == JoAIMode.KIMI_IMAGE_DESCRIBER:
            session.jo_ai_last_image_file_id = largest.file_id
            session.jo_ai_last_image_prompt = prompt_text or None
        else:
            mode = JoAIMode.MENU

    if mode != JoAIMode.KIMI_IMAGE_DESCRIBER:
        await _prompt_uploaded_image_action(message, session_manager, largest.file_id, prompt_text)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="vision",
            user_message=prompt_text or "[photo]",
            bot_reply="Image upload received. Waiting for describe confirmation.",
            model_used=kimi_model,
            success=True,
            message_increment=1,
            feature_used="image_vision",
            media=TrackingMedia(
                media_type="image",
                storage_path=f"telegram_file:{largest.file_id}",
                mime_type="image/jpeg",
                provider_source="telegram",
                media_origin="upload",
                media_status="available",
            ),
        )
        return

    progress_message = await _send_progress_message(message, "Analyzing your image...")
    try:
        description = await _run_kimi_with_progress(
            message,
            _describe_kimi_file_id(
                message,
                chat_service,
                largest.file_id,
                kimi_api_key,
                kimi_model,
                instruction=prompt_text or None,
            ),
        )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        if _is_kimi_unclear_result(str(exc)):
            reply_text = "I could not clearly understand this image. Try another image with better lighting or clarity."
            await message.answer(reply_text, reply_markup=kimi_result_keyboard())
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="vision",
                user_message=prompt_text or "[photo]",
                bot_reply=reply_text,
                model_used=kimi_model,
                success=False,
                message_increment=1,
            )
            return
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            reply_text = "I could not describe this image in time. Please try again."
            await message.answer(reply_text, reply_markup=kimi_result_keyboard())
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="vision",
                user_message=prompt_text or "[photo]",
                bot_reply=reply_text,
                model_used=kimi_model,
                success=False,
                message_increment=1,
            )
            return
        reply_text = _friendly_error_text("JO AI Vision is temporarily unavailable", exc)
        await message.answer(reply_text, reply_markup=kimi_result_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="vision",
            user_message=prompt_text or "[photo]",
            bot_reply=reply_text,
            model_used=kimi_model,
            success=False,
            message_increment=1,
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Failed to download user image.")
        reply_text = "I could not read that image file. Please send another one."
        await message.answer(reply_text)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="vision",
            user_message=prompt_text or "[photo]",
            bot_reply=reply_text,
            model_used=kimi_model,
            success=False,
            message_increment=1,
        )
        return

    await _clear_progress_message(progress_message)
    if not description.strip():
        reply_text = "I could not clearly understand this image. Please try another image."
        await message.answer(reply_text, reply_markup=kimi_result_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="vision",
            user_message=prompt_text or "[photo]",
            bot_reply=reply_text,
            model_used=kimi_model,
            success=False,
            message_increment=1,
        )
        return

    await _send_formatted_ai_reply(message, "chat", description, kimi_result_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="vision",
        user_message=prompt_text or "[photo]",
        bot_reply=description,
        model_used=kimi_model,
        success=True,
        message_increment=1,
    )


@router.callback_query(F.data == "joai:kimi_describe_last")
async def describe_last_uploaded_image(
    query: CallbackQuery,
    session_manager: SessionManager,
    chat_service: ChatService,
    kimi_api_key: str | None,
    kimi_model: str,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    async with session_manager.lock(query.from_user.id) as session:
        last_file_id = session.jo_ai_last_image_file_id
        last_prompt = session.jo_ai_last_image_prompt

    if not last_file_id:
        await query.answer("No uploaded image is available right now.", show_alert=True)
        return

    await session_manager.switch_feature(query.from_user.id, Feature.JO_AI)
    await _switch_to_jo_ai_mode(query.from_user.id, JoAIMode.KIMI_IMAGE_DESCRIBER, session_manager)
    await query.answer("Analyzing image...")
    if not isinstance(query.message, Message):
        return

    progress_message = await _send_progress_message(query.message, "Analyzing your uploaded image...")
    try:
        description = await _run_kimi_with_progress(
            query.message,
            _describe_kimi_file_id(
                query.message,
                chat_service,
                last_file_id,
                kimi_api_key,
                kimi_model,
                instruction=last_prompt,
            ),
        )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        if _is_kimi_unclear_result(str(exc)):
            await query.message.answer(
                "I could not clearly understand this image. Try another image.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            await query.message.answer(
                "I could not describe this image in time. Please try again.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        await query.message.answer(
            _friendly_error_text("JO AI Vision is temporarily unavailable", exc),
            reply_markup=kimi_result_keyboard(),
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Failed to describe stored uploaded image.")
        await query.message.answer("I could not read that image file. Please send another one.")
        return

    await _clear_progress_message(progress_message)
    if not description.strip():
        await query.message.answer(
            "I could not clearly understand this image. Please try another image.",
            reply_markup=kimi_result_keyboard(),
        )
        return

    await _send_formatted_ai_reply(query.message, "chat", description, kimi_result_keyboard())


@router.callback_query(F.data == "joai:kimi_retry")
async def kimi_retry_same_image(
    query: CallbackQuery,
    session_manager: SessionManager,
    chat_service: ChatService,
    kimi_api_key: str | None,
    kimi_model: str,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    async with session_manager.lock(query.from_user.id) as session:
        last_file_id = session.jo_ai_last_image_file_id
        last_prompt = session.jo_ai_last_image_prompt
        mode = session.jo_ai_mode if session.active_feature == Feature.JO_AI else JoAIMode.MENU

    if mode != JoAIMode.KIMI_IMAGE_DESCRIBER or not last_file_id:
        await query.answer("No image to retry. Send a new image first.", show_alert=True)
        return

    await query.answer("Retrying same image...")
    if isinstance(query.message, Message):
        progress_message = await _send_progress_message(query.message, "Re-analyzing the same image...")
        try:
            description = await _run_kimi_with_progress(
                query.message,
                _describe_kimi_file_id(
                    query.message,
                    chat_service,
                    last_file_id,
                    kimi_api_key,
                    kimi_model,
                    instruction=last_prompt,
                ),
            )
        except AIServiceError as exc:
            await _clear_progress_message(progress_message)
            if _is_kimi_unclear_result(str(exc)):
                await query.message.answer(
                    "I still couldn't clearly understand this image.\nTry a clearer image.",
                    reply_markup=kimi_result_keyboard(),
                )
            elif "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
                await query.message.answer(
                    "I couldn't describe this image in time.\nPlease try again.",
                    reply_markup=kimi_result_keyboard(),
                )
            else:
                await query.message.answer(
                    _friendly_error_text("JO AI Vision is temporarily unavailable", exc),
                    reply_markup=kimi_result_keyboard(),
                )
            return
        except Exception:
            await _clear_progress_message(progress_message)
            logger.exception("Unexpected vision retry callback error.")
            await query.message.answer(
                "I couldn't process that image right now.\nPlease try again shortly.",
                reply_markup=kimi_result_keyboard(),
            )
            return

        await _clear_progress_message(progress_message)
        if not description.strip():
            await query.message.answer(
                "I still couldn't clearly understand this image.\nTry another image.",
                reply_markup=kimi_result_keyboard(),
            )
            return
        await _send_formatted_ai_reply(query.message, "chat", description, kimi_result_keyboard())


async def _describe_kimi_file_id(
    message: Message,
    chat_service: ChatService,
    file_id: str,
    kimi_api_key: str | None,
    kimi_model: str,
    instruction: str | None = None,
) -> str:
    file = await message.bot.get_file(file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    image_bytes = file_bytes.read()

    prompt = (instruction or "").strip() or "Describe what you see in this image briefly and clearly."
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            return await chat_service.generate_reply_with_image(
                prompt,
                image_bytes,
                mode="image_describe",
                model_override=kimi_model,
                api_key_override=kimi_api_key,
                thinking=False,
            )
    except AIServiceError:
        # Retry once with a simpler, object-focused instruction.
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            return await chat_service.generate_reply_with_image(
                "What is the main object in this image?",
                image_bytes,
                mode="image_describe",
                model_override=kimi_model,
                api_key_override=kimi_api_key,
                thinking=False,
            )


async def _run_kimi_with_progress(message: Message, work_coro) -> str:
    task = asyncio.create_task(work_coro)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=25)
    except asyncio.TimeoutError:
        await message.answer(
            "? Still working on it...\n"
            "I'm retrying once to extract the image details."
        )
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=25)
        except asyncio.TimeoutError as exc:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise AIServiceError("Vision request timed out.") from exc


def _extract_gemini_command(user_text: str) -> tuple[Literal["chat", "image", "voice"], str]:
    normalized = str(user_text or "").strip()
    if not normalized:
        return "chat", ""
    match = re.match(r"^/(chat|image|img|voice|audio)\b\s*(.*)$", normalized, flags=re.IGNORECASE)
    if not match:
        return "chat", normalized
    command = match.group(1).strip().lower()
    payload = match.group(2).strip()
    mode: Literal["chat", "image", "voice"] = (
        "image"
        if command in {"image", "img"}
        else "voice"
        if command in {"voice", "audio"}
        else "chat"
    )
    if payload:
        return mode, payload
    if mode == "image":
        return mode, "Generate a high-quality image."
    if mode == "voice":
        return mode, "Generate clear speech."
    return mode, normalized


async def _process_gemini_message(
    *,
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    gemini_service: GeminiChatService,
    image_generation_service: ImageGenerationService,
    tts_service: TextToSpeechService,
    tracking_service: SupabaseTrackingService | None,
) -> None:
    reply_markup = jo_chat_keyboard("joai:menu")
    if GEMINI_TEMP_DISABLED:
        reply_text = "Gemini mode is temporarily disabled while image generation is being stabilized."
        await message.answer(reply_text, reply_markup=reply_markup)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gemini",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=gemini_service.model,
            success=False,
            message_increment=1,
            feature_used="gemini_disabled",
        )
        return
    gemini_mode, effective_text = _extract_gemini_command(user_text)
    feature_used = f"gemini_{gemini_mode}"
    guardrail_reply = guardrail_response_for_user_query(effective_text)
    if guardrail_reply:
        await _send_formatted_ai_reply(message, "chat", guardrail_reply, reply_markup)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gemini",
            user_message=effective_text,
            bot_reply=guardrail_reply,
            model_used=gemini_service.model,
            success=not _is_internal_rule_block(guardrail_reply),
            message_increment=1,
            feature_used=feature_used,
        )
        return

    if gemini_mode == "image":
        progress_message = await _send_progress_message(message, "Generating Gemini image...")
        try:
            async with ChatActionSender.upload_photo(bot=message.bot, chat_id=message.chat.id):
                generated = await image_generation_service.generate_image(
                    effective_text,
                    size=IMAGE_RATIO_TO_SIZE["1:1"],
                    ratio="1:1",
                )
        except AIServiceError as exc:
            await _clear_progress_message(progress_message)
            reply_text = _friendly_error_text("Gemini image mode is temporarily unavailable", exc)
            await message.answer(reply_text, reply_markup=reply_markup)
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="gemini",
                user_message=effective_text,
                bot_reply=reply_text,
                model_used=gemini_service.model,
                success=False,
                image_increment=1,
                feature_used=feature_used,
            )
            return
        except Exception:
            await _clear_progress_message(progress_message)
            logger.exception("Unexpected Gemini image generation error.")
            reply_text = _friendly_error_text("Unexpected Gemini image error")
            await message.answer(reply_text, reply_markup=reply_markup)
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="gemini",
                user_message=effective_text,
                bot_reply=reply_text,
                model_used=gemini_service.model,
                success=False,
                image_increment=1,
                feature_used=feature_used,
            )
            return

        await _clear_progress_message(progress_message)
        if generated.image_bytes:
            image_file = BufferedInputFile(generated.image_bytes, filename="gemini_generated.png")
            sent = await message.answer_photo(
                photo=image_file,
                caption="<b>Gemini image is ready.</b>",
                reply_markup=reply_markup,
            )
            storage_path = f"telegram_file:{sent.photo[-1].file_id}" if sent.photo else None
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="gemini",
                user_message=effective_text,
                bot_reply="Gemini image is ready.",
                model_used=gemini_service.model,
                success=True,
                image_increment=1,
                feature_used=feature_used,
                media=TrackingMedia(
                    media_type="image",
                    media_url=generated.image_url,
                    storage_path=storage_path,
                    mime_type="image/png",
                    provider_source="gemini",
                    media_origin="generated",
                    media_status="available",
                ),
            )
            return
        if generated.image_url:
            sent = await message.answer_photo(
                photo=generated.image_url,
                caption="<b>Gemini image is ready.</b>",
                reply_markup=reply_markup,
            )
            storage_path = f"telegram_file:{sent.photo[-1].file_id}" if sent.photo else None
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="gemini",
                user_message=effective_text,
                bot_reply="Gemini image is ready.",
                model_used=gemini_service.model,
                success=True,
                image_increment=1,
                feature_used=feature_used,
                media=TrackingMedia(
                    media_type="image",
                    media_url=generated.image_url,
                    storage_path=storage_path,
                    provider_source="gemini",
                    media_origin="generated",
                    media_status="available",
                ),
            )
            return
        reply_text = "Gemini image mode did not return an image payload."
        await message.answer(reply_text, reply_markup=reply_markup)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gemini",
            user_message=effective_text,
            bot_reply=reply_text,
            model_used=gemini_service.model,
            success=False,
            image_increment=1,
            feature_used=feature_used,
        )
        return

    if gemini_mode == "voice":
        progress_message = await _send_progress_message(message, "Generating Gemini voice...")
        try:
            async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
                generated = await tts_service.generate_speech(
                    text=effective_text,
                    language="en",
                    voice="female",
                    emotion="neutral",
                )
        except AIServiceError as exc:
            await _clear_progress_message(progress_message)
            reply_text = _friendly_error_text("Gemini voice mode is temporarily unavailable", exc)
            await message.answer(reply_text, reply_markup=reply_markup)
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="gemini",
                user_message=effective_text,
                bot_reply=reply_text,
                model_used=gemini_service.model,
                success=False,
                message_increment=1,
                feature_used=feature_used,
            )
            return
        except Exception:
            await _clear_progress_message(progress_message)
            logger.exception("Unexpected Gemini voice generation error.")
            reply_text = _friendly_error_text("Unexpected Gemini voice error")
            await message.answer(reply_text, reply_markup=reply_markup)
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="gemini",
                user_message=effective_text,
                bot_reply=reply_text,
                model_used=gemini_service.model,
                success=False,
                message_increment=1,
                feature_used=feature_used,
            )
            return

        await _clear_progress_message(progress_message)
        extension = _tts_extension_for_mime_type(generated.mime_type)
        audio_file = BufferedInputFile(generated.audio_bytes, filename=f"gemini_voice.{extension}")
        await message.answer_audio(
            audio=audio_file,
            caption="<b>Gemini voice is ready.</b>",
            reply_markup=reply_markup,
        )
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gemini",
            user_message=effective_text,
            bot_reply="Gemini voice is ready.",
            model_used=gemini_service.model,
            success=True,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="audio",
                mime_type=generated.mime_type,
                provider_source="gemini",
                media_origin="generated",
                media_status="available",
            ),
        )
        return

    progress_message = await _send_progress_message(message, "Generating Gemini response...")
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            reply_text = await gemini_service.generate_reply(effective_text)
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        error_text = _friendly_error_text("Gemini mode is temporarily unavailable", exc)
        await message.answer(error_text, reply_markup=reply_markup)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gemini",
            user_message=effective_text,
            bot_reply=error_text,
            model_used=gemini_service.model,
            success=False,
            message_increment=1,
            feature_used=feature_used,
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected Gemini generation error.")
        error_text = _friendly_error_text("Unexpected Gemini error")
        await message.answer(error_text, reply_markup=reply_markup)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gemini",
            user_message=effective_text,
            bot_reply=error_text,
            model_used=gemini_service.model,
            success=False,
            message_increment=1,
            feature_used=feature_used,
        )
        return

    await _clear_progress_message(progress_message)
    if message.from_user:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature == Feature.JO_AI and session.jo_ai_mode == JoAIMode.GEMINI:
                session.jo_ai_chat_history.append(("user", _compact_history_entry(effective_text)))
                session.jo_ai_chat_history.append(("assistant", _compact_history_entry(reply_text)))

    await _send_formatted_ai_reply(message, "chat", reply_text, reply_markup)
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="gemini",
        user_message=effective_text,
        bot_reply=reply_text,
        model_used=gemini_service.model,
        success=True,
        message_increment=1,
        feature_used=feature_used,
    )


async def _process_chat_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    history: list[dict[str, str]],
    mode: Literal["chat", "code", "research", "prompt", "image_prompt"],
    mode_options: dict[str, object],
    reply_markup: InlineKeyboardMarkup | None = None,
    tracking_service: SupabaseTrackingService | None = None,
    tracking_message_type: str | None = None,
    tracking_user_message: str | None = None,
) -> None:
    keyboard = reply_markup or jo_chat_keyboard()
    effective_message_type = (tracking_message_type or mode).strip() or mode
    tracked_user_message = (tracking_user_message or "").strip() or user_text
    if not tracked_user_message.strip():
        tracked_user_message = _tracking_text_from_message(message, "[message]")
    model_used = _chat_model_used(chat_service, mode_options)
    guardrail_reply = guardrail_response_for_user_query(user_text, tracked_user_message)
    if guardrail_reply:
        await _send_formatted_ai_reply(message, "chat", guardrail_reply, keyboard)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type=effective_message_type,
            user_message=tracked_user_message,
            bot_reply=guardrail_reply,
            model_used=model_used,
            success=not _is_internal_rule_block(guardrail_reply),
            message_increment=1,
        )
        return

    show_progress_message = mode not in {"chat", "code"}
    if show_progress_message:
        await _maybe_send_engagement(message)
    progress_message: Message | None = None
    if show_progress_message:
        progress_text = MODE_PROGRESS_TEXT.get(mode, "Working on it...")
        progress_message = await _send_progress_message(message, progress_text)
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            reply = await chat_service.generate_reply(
                user_text,
                history=history,
                mode=mode,
                model_override=mode_options.get("model_override"),  # type: ignore[arg-type]
                api_key_override=mode_options.get("api_key_override"),  # type: ignore[arg-type]
                thinking=bool(mode_options.get("thinking", False)),
            )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        reply_text = _friendly_error_text("AI is unavailable right now", exc)
        await message.answer(reply_text, reply_markup=keyboard)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type=effective_message_type,
            user_message=tracked_user_message,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected JO AI error.")
        reply_text = _friendly_error_text("Unexpected AI failure")
        await message.answer(reply_text, reply_markup=keyboard)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type=effective_message_type,
            user_message=tracked_user_message,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return

    await _clear_progress_message(progress_message)
    if message.from_user:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature == Feature.JO_AI and session.jo_ai_mode == JoAIMode.CHAT:
                session.jo_ai_chat_history.append(("user", _compact_history_entry(user_text)))
                session.jo_ai_chat_history.append(("assistant", _compact_history_entry(reply)))
    await _send_formatted_ai_reply(message, mode, reply, keyboard)
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type=effective_message_type,
        user_message=tracked_user_message,
        bot_reply=reply,
        model_used=model_used,
        success=True,
        message_increment=1,
    )


def _tts_extension_for_mime_type(mime_type: str) -> str:
    normalized = (mime_type or "").strip().lower()
    if normalized in {"audio/wav", "audio/x-wav"}:
        return "wav"
    if normalized == "audio/ogg":
        return "ogg"
    if normalized == "audio/webm":
        return "webm"
    if normalized == "audio/flac":
        return "flac"
    return "mp3"


async def _process_tts_message(
    message: Message,
    user_text: str,
    tts_service: TextToSpeechService,
    language: str | None,
    voice: str | None,
    style: str | None,
    emotion: str | None,
    tracking_service: SupabaseTrackingService | None,
) -> None:
    model_used = (tts_service.function_id or "").strip() or None
    selected_language = (language or "").strip().lower()
    if selected_language not in TTS_LANGUAGE_LABELS:
        reply_text = "Step 1/4: Choose a language first."
        await message.answer(reply_text, reply_markup=tts_language_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="tts",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return

    selected_voice = (voice or "").strip().lower()
    if selected_voice not in TTS_VOICE_LABELS:
        reply_text = "Step 2/4: Choose male or female first."
        await message.answer(reply_text, reply_markup=tts_voice_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="tts",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return

    selected_style = (style or "").strip().lower()
    selected_emotion = (emotion or "").strip().lower()
    if not selected_style or selected_emotion not in TTS_EMOTION_LABELS:
        reply_text = "Step 3/4: Choose a voice style first."
        await message.answer(reply_text, reply_markup=tts_style_keyboard(_tts_style_choices(selected_voice)))
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="tts",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return

    progress_message = await _send_progress_message(message, "Generating speech...")
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            generated = await tts_service.generate_speech(
                text=user_text,
                language=selected_language,
                voice=selected_voice,
                emotion=selected_emotion,
            )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        reply_text = _friendly_error_text("Text-to-Speech is temporarily unavailable", exc)
        await message.answer(reply_text, reply_markup=_tts_text_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="tts",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected TTS generation error.")
        reply_text = _friendly_error_text("Unexpected Text-to-Speech error")
        await message.answer(reply_text, reply_markup=_tts_text_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="tts",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return

    await _clear_progress_message(progress_message)
    extension = _tts_extension_for_mime_type(generated.mime_type)
    audio_file = BufferedInputFile(generated.audio_bytes, filename=f"jo_ai_tts.{extension}")
    language_label = TTS_LANGUAGE_LABELS.get(selected_language, selected_language)
    voice_label = TTS_VOICE_LABELS.get(selected_voice, selected_voice)
    style_label = _tts_style_label(selected_voice, selected_style)
    await message.answer_audio(
        audio=audio_file,
        caption=(
            "<b>Speech is ready</b>\n\n"
            f"Language: <b>{html.escape(language_label)}</b>\n"
            f"Voice: <b>{html.escape(voice_label)}</b>\n"
            f"Style: <b>{html.escape(style_label)}</b>"
        ),
        reply_markup=_tts_text_reply_keyboard(),
    )
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="tts",
        user_message=user_text,
        bot_reply="Speech is ready",
        model_used=model_used,
        success=True,
        message_increment=1,
    )


async def _process_prompt_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    chat_service: ChatService,
    current_prompt_type: str | None,
    mode_options: dict[str, object],
    tracking_service: SupabaseTrackingService | None,
) -> None:
    model_used = _chat_model_used(chat_service, mode_options)
    if not message.from_user:
        return
    if not current_prompt_type:
        async with session_manager.lock(message.from_user.id) as session:
            if session.active_feature != Feature.JO_AI or session.jo_ai_mode != JoAIMode.PROMPT:
                reply_text = "Prompt session expired. Send /prompt to start again."
                await message.answer(reply_text)
                await _track_telegram_action(
                    tracking_service=tracking_service,
                    message=message,
                    message_type="prompt",
                    user_message=user_text,
                    bot_reply=reply_text,
                    model_used=model_used,
                    success=False,
                    message_increment=1,
                )
                return
            session.jo_ai_prompt_type = user_text
        await _send_prompt_details_step(message)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="prompt_setup",
            user_message=user_text,
            bot_reply="Prompt type saved. Waiting for details.",
            model_used=model_used,
            success=True,
            message_increment=1,
        )
        return

    await _maybe_send_engagement(message)
    prompt_request = f"Prompt type: {current_prompt_type}\nUser goal/details: {user_text}\nGenerate one optimized prompt."
    progress_message = await _send_progress_message(message, "Generating your optimized prompt...")
    try:
        prompt_output = await chat_service.generate_reply(
            prompt_request,
            history=[],
            mode="prompt",
            model_override=mode_options.get("model_override"),  # type: ignore[arg-type]
            api_key_override=mode_options.get("api_key_override"),  # type: ignore[arg-type]
            thinking=bool(mode_options.get("thinking", False)),
        )
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        reply_text = _friendly_error_text("Prompt generation failed", exc)
        await message.answer(reply_text, reply_markup=_prompt_details_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="prompt",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected prompt generation error.")
        reply_text = _friendly_error_text("Unexpected prompt generation error")
        await message.answer(reply_text, reply_markup=_prompt_details_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="prompt",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
        )
        return
    await _clear_progress_message(progress_message)
    await _send_formatted_ai_reply(message, "prompt", prompt_output, _prompt_details_reply_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="prompt",
        user_message=user_text,
        bot_reply=prompt_output,
        model_used=model_used,
        success=True,
        message_increment=1,
    )


async def _process_image_message(
    message: Message,
    user_text: str,
    session_manager: SessionManager,
    image_generation_service: ImageGenerationService,
    pollinations_media_service: PollinationsMediaService,
    current_image_ratio: str | None,
    current_image_model: str | None,
    tracking_service: SupabaseTrackingService | None,
) -> None:
    _ = session_manager
    model_option = _resolve_image_model_option(current_image_model)
    model_label = _image_model_label(model_option)
    provider_source = "jo_ai" if model_option == IMAGE_MODEL_OPTION_JO else "pollinations"
    feature_used = f"image_generation:{model_option}"
    ratio_label = current_image_ratio if current_image_ratio in IMAGE_RATIO_TO_SIZE else "1:1"
    image_size = IMAGE_RATIO_TO_SIZE.get(ratio_label, IMAGE_RATIO_TO_SIZE["1:1"])
    guardrail_reply = guardrail_response_for_user_query(user_text, ratio_label)
    if guardrail_reply:
        reply_text = guardrail_reply if not _is_internal_rule_block(guardrail_reply) else _image_request_blocked_text()
        await message.answer(reply_text, reply_markup=_image_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="image",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_label,
            success=False,
            image_increment=1,
            feature_used=feature_used,
        )
        return

    await _maybe_send_engagement(message)
    enhanced_prompt = build_enhanced_image_prompt(user_text, ratio=ratio_label) or user_text
    prompt_hash = hashlib.sha256(user_text.encode("utf-8")).hexdigest()[:12]
    logger.info(
        "TELEGRAM IMAGE ENHANCED | user=%s ratio=%s prompt_hash=%s enhanced_len=%s",
        message.from_user.id if message.from_user else "unknown",
        ratio_label,
        prompt_hash,
        len(enhanced_prompt),
    )

    progress_message = await _send_progress_message(message, "Creating your image...")

    try:
        async with ChatActionSender.upload_photo(bot=message.bot, chat_id=message.chat.id):
            generated = await asyncio.wait_for(
                (
                    image_generation_service.generate_image(
                        enhanced_prompt,
                        size=image_size,
                        ratio=ratio_label,
                    )
                    if model_option == IMAGE_MODEL_OPTION_JO
                    else pollinations_media_service.generate_image(
                        prompt=enhanced_prompt,
                        model=(
                            pollinations_media_service.image_model_chat_gbt
                            if model_option == IMAGE_MODEL_OPTION_CHAT_GBT
                            else pollinations_media_service.image_model_grok_imagine
                        ),
                        size=image_size,
                        enhance=True,
                    )
                ),
                timeout=TELEGRAM_IMAGE_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        await _clear_progress_message(progress_message)
        reply_text = "Image generation timed out. Please retry."
        await message.answer(reply_text, reply_markup=_image_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="image",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_label,
            success=False,
            image_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="image",
                provider_source=provider_source,
                media_origin="generated",
                media_status="failed",
                media_error_reason="timeout",
            ),
        )
        return
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        if _is_internal_rule_block(str(exc)):
            reply_text = _image_request_blocked_text()
            await message.answer(reply_text, reply_markup=_image_prompt_reply_keyboard())
            await _track_telegram_action(
                tracking_service=tracking_service,
                message=message,
                message_type="image",
                user_message=user_text,
                bot_reply=reply_text,
                model_used=model_label,
                success=False,
                image_increment=1,
                feature_used=feature_used,
                media=TrackingMedia(
                    media_type="image",
                    provider_source=provider_source,
                    media_origin="generated",
                    media_status="failed",
                    media_error_reason=reply_text,
                ),
            )
            return
        primary_image_key = (
            image_generation_service.api_key
            if model_option == IMAGE_MODEL_OPTION_JO
            else pollinations_media_service.api_key
        )
        reply_text = _image_generation_failed_text(
            confirmed_unavailable=_is_service_unavailable_error(exc) or not bool(primary_image_key),
        )
        await message.answer(reply_text, reply_markup=_image_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="image",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_label,
            success=False,
            image_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="image",
                provider_source=provider_source,
                media_origin="generated",
                media_status="failed",
                media_error_reason=reply_text,
            ),
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected image generation error.")
        reply_text = _image_generation_failed_text(confirmed_unavailable=False)
        await message.answer(reply_text, reply_markup=_image_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="image",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_label,
            success=False,
            image_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="image",
                provider_source=provider_source,
                media_origin="generated",
                media_status="failed",
                media_error_reason=reply_text,
            ),
        )
        return

    await _clear_progress_message(progress_message)
    original_prompt_caption = html.escape(" ".join(user_text.split())[:900]) or "Image generated."
    if generated.image_bytes:
        image_file = BufferedInputFile(generated.image_bytes, filename="jo_ai_generated.png")
        sent = await message.answer_photo(
            photo=image_file,
            caption=original_prompt_caption,
            reply_markup=_image_prompt_reply_keyboard(),
        )
        storage_path = None
        if sent.photo:
            storage_path = f"telegram_file:{sent.photo[-1].file_id}"
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="image",
            user_message=user_text,
            bot_reply="Image generated successfully.",
            model_used=model_label,
            success=True,
            image_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="image",
                media_url=generated.image_url,
                storage_path=storage_path,
                mime_type="image/png",
                provider_source=provider_source,
                media_origin="generated",
                media_status="available",
            ),
        )
        return

    if generated.image_url:
        sent = await message.answer_photo(
            photo=generated.image_url,
            caption=original_prompt_caption,
            reply_markup=_image_prompt_reply_keyboard(),
        )
        storage_path = None
        if sent.photo:
            storage_path = f"telegram_file:{sent.photo[-1].file_id}"
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="image",
            user_message=user_text,
            bot_reply="Image generated successfully.",
            model_used=model_label,
            success=True,
            image_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="image",
                media_url=generated.image_url,
                storage_path=storage_path,
                provider_source=provider_source,
                media_origin="generated",
                media_status="available",
            ),
        )
        return

    reply_text = _image_generation_failed_text(confirmed_unavailable=True)
    await message.answer(reply_text, reply_markup=_image_prompt_reply_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="image",
        user_message=user_text,
        bot_reply=reply_text,
        model_used=model_label,
        success=False,
        image_increment=1,
        feature_used=feature_used,
        media=TrackingMedia(
            media_type="image",
            provider_source=provider_source,
            media_origin="generated",
            media_status="missing",
            media_error_reason="image payload missing",
        ),
    )


async def _process_gpt_audio_message(
    message: Message,
    user_text: str,
    pollinations_media_service: PollinationsMediaService,
    tracking_service: SupabaseTrackingService | None,
) -> None:
    feature_used = "gpt_audio"
    guardrail_reply = guardrail_response_for_user_query(user_text)
    if guardrail_reply:
        reply_text = guardrail_reply if not _is_internal_rule_block(guardrail_reply) else _image_request_blocked_text()
        await message.answer(reply_text, reply_markup=jo_chat_keyboard("joai:menu"))
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gpt_audio",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            feature_used=feature_used,
        )
        return

    enhanced_prompt = (
        "Answer the user request with a clear spoken explanation.\n"
        "Keep it natural, concise, and helpful.\n\n"
        f"User request: {user_text}"
    )
    progress_message = await _send_progress_message(message, "Generating your GPT Audio...")
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            generated = await asyncio.wait_for(
                pollinations_media_service.generate_audio(
                    prompt=enhanced_prompt,
                    model=pollinations_media_service.audio_model_gpt_audio,
                    voice=pollinations_media_service.audio_voice_gpt_audio,
                    enhance=True,
                ),
                timeout=GPT_AUDIO_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        await _clear_progress_message(progress_message)
        reply_text = "Audio generation timed out. Please try again."
        await message.answer(reply_text, reply_markup=jo_chat_keyboard("joai:menu"))
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gpt_audio",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="audio",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason="timeout",
            ),
        )
        return
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        reply_text = _friendly_error_text("GPT Audio is temporarily unavailable", exc)
        await message.answer(reply_text, reply_markup=jo_chat_keyboard("joai:menu"))
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gpt_audio",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="audio",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason=reply_text,
            ),
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected GPT Audio generation error.")
        reply_text = _friendly_error_text("Unexpected GPT Audio generation error")
        await message.answer(reply_text, reply_markup=jo_chat_keyboard("joai:menu"))
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="gpt_audio",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="audio",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason=reply_text,
            ),
        )
        return

    await _clear_progress_message(progress_message)
    extension = generated.file_extension if generated.file_extension else "mp3"
    audio_file = BufferedInputFile(generated.audio_bytes, filename=f"jo_ai_gpt_audio.{extension}")
    sent = await message.answer_audio(
        audio=audio_file,
        caption="Your GPT Audio response is ready.",
        reply_markup=jo_chat_keyboard("joai:menu"),
    )
    storage_path = f"telegram_file:{sent.audio.file_id}" if sent.audio else None
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="gpt_audio",
        user_message=user_text,
        bot_reply="GPT Audio generated successfully.",
        model_used=GPT_AUDIO_MODEL_LABEL,
        success=True,
        message_increment=1,
        feature_used=feature_used,
        media=TrackingMedia(
            media_type="audio",
            storage_path=storage_path,
            mime_type=generated.mime_type,
            provider_source="pollinations",
            media_origin="generated",
            media_status="available",
        ),
    )


async def _process_video_message(
    message: Message,
    user_text: str,
    pollinations_media_service: PollinationsMediaService,
    current_duration_seconds: int | None,
    current_aspect_ratio: str | None,
    tracking_service: SupabaseTrackingService | None,
) -> None:
    duration_seconds = int(current_duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS)
    if duration_seconds not in VIDEO_DURATION_OPTIONS:
        duration_seconds = DEFAULT_VIDEO_DURATION_SECONDS
    aspect_ratio = (
        str(current_aspect_ratio).strip()
        if str(current_aspect_ratio or "").strip() in VIDEO_ASPECT_RATIO_OPTIONS
        else DEFAULT_VIDEO_ASPECT_RATIO
    )
    model_used = VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO
    feature_used = "video_generation:grok_text_to_video"
    if message.from_user and not await _is_video_generation_allowed(message.bot, message.from_user.id):
        reply_text = _video_join_required_text()
        await _send_video_join_required_step(message)
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
            feature_used=feature_used,
        )
        return
    guardrail_reply = guardrail_response_for_user_query(user_text, aspect_ratio, str(duration_seconds))
    if guardrail_reply:
        reply_text = guardrail_reply if not _is_internal_rule_block(guardrail_reply) else _image_request_blocked_text()
        await message.answer(reply_text, reply_markup=_video_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
            feature_used=feature_used,
        )
        return

    await _maybe_send_engagement(message)
    enhanced_prompt = build_enhanced_video_prompt(
        user_text,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
    ) or user_text

    progress_message = await _send_progress_message(message, "Creating your video...")
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            generated = await asyncio.wait_for(
                pollinations_media_service.generate_video(
                    prompt=enhanced_prompt,
                    model=pollinations_media_service.video_model_grok_text_to_video,
                    duration_seconds=duration_seconds,
                    aspect_ratio=aspect_ratio,
                    enhance=True,
                    audio=False,
                ),
                timeout=TELEGRAM_VIDEO_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        await _clear_progress_message(progress_message)
        reply_text = "Video generation timed out. Please retry."
        await message.answer(reply_text, reply_markup=_video_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="video",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason="timeout",
            ),
        )
        return
    except AIServiceError as exc:
        await _clear_progress_message(progress_message)
        reply_text = _friendly_error_text("Video generation is temporarily unavailable", exc)
        await message.answer(reply_text, reply_markup=_video_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="video",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason=reply_text,
            ),
        )
        return
    except Exception:
        await _clear_progress_message(progress_message)
        logger.exception("Unexpected video generation error.")
        reply_text = _friendly_error_text("Unexpected video generation error")
        await message.answer(reply_text, reply_markup=_video_prompt_reply_keyboard())
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply=reply_text,
            model_used=model_used,
            success=False,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="video",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason=reply_text,
            ),
        )
        return

    await _clear_progress_message(progress_message)
    caption = (
        f"<b>{VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO}</b>\n"
        f"Duration: <b>{duration_seconds}s</b> | Ratio: <b>{html.escape(aspect_ratio)}</b>"
    )

    if generated.video_bytes:
        file_name = "jo_ai_video.mp4"
        if (generated.mime_type or "").lower() == "video/webm":
            file_name = "jo_ai_video.webm"
        video_file = BufferedInputFile(generated.video_bytes, filename=file_name)
        sent = await message.answer_video(
            video=video_file,
            caption=caption,
            reply_markup=_video_prompt_reply_keyboard(),
        )
        storage_path = f"telegram_file:{sent.video.file_id}" if sent.video else None
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply="Video generated successfully.",
            model_used=model_used,
            success=True,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="video",
                media_url=generated.video_url,
                storage_path=storage_path,
                mime_type=generated.mime_type,
                provider_source="pollinations",
                media_origin="generated",
                media_status="available",
            ),
        )
        return

    if generated.video_url:
        sent = await message.answer_video(
            video=generated.video_url,
            caption=caption,
            reply_markup=_video_prompt_reply_keyboard(),
        )
        storage_path = f"telegram_file:{sent.video.file_id}" if sent.video else None
        await _track_telegram_action(
            tracking_service=tracking_service,
            message=message,
            message_type="video",
            user_message=user_text,
            bot_reply="Video generated successfully.",
            model_used=model_used,
            success=True,
            message_increment=1,
            feature_used=feature_used,
            media=TrackingMedia(
                media_type="video",
                media_url=generated.video_url,
                storage_path=storage_path,
                mime_type=generated.mime_type,
                provider_source="pollinations",
                media_origin="generated",
                media_status="available",
            ),
        )
        return

    reply_text = "Video generation did not return a playable result."
    await message.answer(reply_text, reply_markup=_video_prompt_reply_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="video",
        user_message=user_text,
        bot_reply=reply_text,
        model_used=model_used,
        success=False,
        message_increment=1,
        feature_used=feature_used,
        media=TrackingMedia(
            media_type="video",
            provider_source="pollinations",
            media_origin="generated",
            media_status="missing",
            media_error_reason="video payload missing",
        ),
    )


@router.message(ActiveFeatureFilter(Feature.JO_AI))
async def jo_ai_unexpected_input(
    message: Message,
    tracking_service: SupabaseTrackingService | None = None,
) -> None:
    reply_text = (
        "Send text in the current JO AI mode.\n"
        "In Code Generator mode, you can upload a code file for debug/fix.\n"
        "In Video Generation mode, set duration/ratio then send a prompt.\n"
        "In Vision mode, send an image.\n"
        "In Text-to-Speech mode, choose language, voice, and style first.\n"
        "In GPT Audio mode, send any question or prompt.\n"
        "You can switch mode anytime."
    )
    await message.answer(reply_text, reply_markup=jo_ai_menu_keyboard())
    await _track_telegram_action(
        tracking_service=tracking_service,
        message=message,
        message_type="jo_ai_unexpected",
        user_message=_tracking_text_from_message(message, "[unexpected input]"),
        bot_reply=reply_text,
        model_used=None,
        success=False,
        message_increment=1,
    )

