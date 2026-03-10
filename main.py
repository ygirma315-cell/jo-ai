from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
import json
import logging
import os
import re
import time
import uuid
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import uvicorn
from aiogram.types import Update
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from supabase import create_client

from bot.app import (
    BotRuntime,
    close_bot_runtime,
    create_bot_runtime,
    process_telegram_update,
    start_telegram_startup_tasks,
)
from bot.config import load_settings
from bot.logging_config import setup_logging
from bot.runtime_info import build_runtime_info
from bot.services.ai_service import AIServiceError, ChatService, ImageGenerationService, TextToSpeechService
from bot.services.supabase_client import build_supabase_config
from bot.services.tracking_service import SupabaseTrackingService, TrackingIdentity
from bot.security import (
    SAFE_INTERNAL_DETAILS_REFUSAL,
    SAFE_SERVICE_UNAVAILABLE_MESSAGE,
    build_safe_version_summary,
    contains_internal_detail_request,
)
from version import VERSION, WEB_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_GITHUB_PAGES_URL = "https://ygirma315-cell.github.io/jo-ai/"
DEFAULT_LOCAL_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
)
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)
TextMode = Literal["chat", "code", "research", "prompt", "deep_analysis"]
CODE_FENCE_PATTERN = re.compile(r"```(?P<lang>[a-zA-Z0-9_+#.-]*)\n(?P<code>[\s\S]*?)```", re.MULTILINE)
DEBUG_INTENT_PATTERN = re.compile(
    r"\b(debug|fix|error|exception|traceback|bug|issue|crash|failing|failure|broken|not working)\b",
    flags=re.IGNORECASE,
)
IMAGE_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "16:9": "1344x768",
    "9:16": "768x1344",
}
IMAGE_SIZE_TO_RATIO = {value: key for key, value in IMAGE_RATIO_TO_SIZE.items()}
IMAGE_STYLE_HINTS = {
    "realistic": "photorealistic, natural textures, realistic camera lens, ultra detailed",
    "ai_art": "digital art, stylized illustration, painterly texture, artistic composition",
    "anime": "anime style, clean line art, expressive characters, vibrant colors",
    "cyberpunk": "cyberpunk, neon lighting, futuristic city, rain reflections, cinematic mood",
    "logo_icon": "minimal clean logo design, centered icon, vector style, brand-ready composition",
    "render_3d": "3D render, physically based materials, global illumination, high detail",
    "concept_art": "concept art, environment storytelling, dramatic composition, matte painting quality",
}
OBSERVABLE_REQUEST_PATHS = frozenset(
    {
        "/ai",
        "/chat",
        "/code",
        "/research",
        "/prompt",
        "/image",
        "/vision",
        "/tts",
        "/telegram/webhook",
        "/debug/supabase-test",
    }
)


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TrackingRequestBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    telegram_id: int | None = Field(default=None, gt=0)
    username: str | None = Field(default=None, max_length=128)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)


class ChatRequest(TrackingRequestBase):
    message: str = Field(min_length=1, max_length=32000)


class CodeRequest(ChatRequest):
    code_file_name: str | None = Field(default=None, max_length=240)
    code_file_base64: str | None = Field(default=None, max_length=4_000_000)


class ImageRequest(TrackingRequestBase):
    prompt: str | None = Field(default=None, max_length=4000)
    message: str | None = Field(default=None, max_length=4000)
    image_type: str | None = Field(default=None, max_length=60)
    ratio: Literal["1:1", "16:9", "9:16"] | None = Field(default=None)
    size: str | None = Field(default=None, pattern=r"^\d+x\d+$")

    @model_validator(mode="after")
    def _validate_prompt(self) -> "ImageRequest":
        if not self.prompt and not self.message:
            raise ValueError("Either 'prompt' or 'message' must be provided.")
        return self

    @property
    def effective_prompt(self) -> str:
        return self.prompt or self.message or ""

    @property
    def effective_ratio(self) -> Literal["1:1", "16:9", "9:16"]:
        if self.ratio in IMAGE_RATIO_TO_SIZE:
            return self.ratio
        inferred = IMAGE_SIZE_TO_RATIO.get((self.size or "").strip())
        if inferred in IMAGE_RATIO_TO_SIZE:
            return inferred  # type: ignore[return-value]
        return "1:1"

    @property
    def effective_size(self) -> str:
        return IMAGE_RATIO_TO_SIZE[self.effective_ratio]

    @property
    def effective_style_hint(self) -> str:
        key = (self.image_type or "").strip().lower()
        return IMAGE_STYLE_HINTS.get(key, "")


class PromptRequest(TrackingRequestBase):
    message: str = Field(min_length=1, max_length=32000)
    prompt_type: str | None = Field(default=None, max_length=120)

    @property
    def effective_prompt_type(self) -> str:
        return self.prompt_type or "general"


class AITextRequest(TrackingRequestBase):
    mode: TextMode = "chat"
    message: str = Field(min_length=1, max_length=32000)
    prompt_type: str | None = Field(default=None, max_length=120)
    code_file_name: str | None = Field(default=None, max_length=240)
    code_file_base64: str | None = Field(default=None, max_length=4_000_000)

    @property
    def effective_prompt_type(self) -> str:
        return self.prompt_type or "general"


class VisionDescribeRequest(TrackingRequestBase):
    message: str | None = Field(default=None, max_length=2000)
    image_base64: str = Field(min_length=1, max_length=15_000_000)

    @property
    def effective_message(self) -> str:
        return self.message or "Describe this image."


class TTSRequest(TrackingRequestBase):
    text: str | None = Field(default=None, max_length=12000)
    message: str | None = Field(default=None, max_length=12000)
    language: str | None = Field(default="en", max_length=16)
    voice: str | None = Field(default="female", max_length=32)
    emotion: str | None = Field(default="neutral", max_length=32)

    @model_validator(mode="after")
    def _validate_text(self) -> "TTSRequest":
        if not self.text and not self.message:
            raise ValueError("Either 'text' or 'message' must be provided.")
        return self

    @property
    def effective_text(self) -> str:
        return self.text or self.message or ""

    @property
    def effective_language(self) -> str:
        value = (self.language or "en").strip().lower()
        if value in {"en", "en-us", "english"}:
            return "en"
        if value in {"es", "es-es", "spanish"}:
            return "es"
        if value in {"fr", "fr-fr", "french"}:
            return "fr"
        return "en"

    @property
    def effective_voice(self) -> str:
        value = (self.voice or "female").strip().lower()
        if value in {"male", "man"}:
            return "male"
        return "female"

    @property
    def effective_emotion(self) -> str:
        value = (self.emotion or "neutral").strip().lower()
        allowed = {"neutral", "cheerful", "calm", "serious"}
        if value in allowed:
            return value
        aliases = {
            "natural": "neutral",
            "friendly": "neutral",
            "happy": "cheerful",
            "excited": "cheerful",
            "bright": "cheerful",
            "energetic": "cheerful",
            "relaxed": "calm",
            "soft": "calm",
            "warm": "calm",
            "formal": "serious",
            "focused": "serious",
            "deep": "serious",
            "narrator": "serious",
        }
        return aliases.get(value, "neutral")


def _read_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _origin_from_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _cors_origins_from_env() -> list[str]:
    raw = _read_env("ALLOWED_ORIGINS")
    values: list[str] = []

    if raw:
        for item in raw.split(","):
            candidate = item.strip()
            if not candidate:
                continue
            if candidate == "*":
                return ["*"]
            origin = _origin_from_url(candidate)
            if origin and origin not in values:
                values.append(origin)

    for candidate in (
        _read_env("PUBLIC_BASE_URL"),
        _read_env("RENDER_EXTERNAL_URL"),
        _read_env("MINIAPP_URL") or DEFAULT_GITHUB_PAGES_URL,
    ):
        origin = _origin_from_url(candidate)
        if origin and origin not in values:
            values.append(origin)

    for origin in DEFAULT_LOCAL_ORIGINS:
        if origin not in values:
            values.append(origin)

    return values or ["*"]


@lru_cache(maxsize=1)
def get_settings():
    return load_settings()


def _safe_service_error(status_code: int = 502) -> BackendError:
    return BackendError(SAFE_SERVICE_UNAVAILABLE_MESSAGE, status_code=status_code)


def _safe_refusal_response() -> JSONResponse:
    return JSONResponse(status_code=200, content={"output": SAFE_INTERNAL_DETAILS_REFUSAL})


def _maybe_block_sensitive_request(*parts: str | None) -> JSONResponse | None:
    if contains_internal_detail_request(*parts):
        return _safe_refusal_response()
    return None


def _compose_prompt_request(prompt_type: str, message: str) -> str:
    return (
        f"Prompt type: {prompt_type}\n"
        f"User requirements:\n{message}\n\n"
        "Return exactly one optimized prompt that is specific and reusable."
    )


def _is_observable_request_path(path: str) -> bool:
    raw_path = str(path or "").strip()
    return raw_path in OBSERVABLE_REQUEST_PATHS or raw_path.startswith("/api/")


def _request_id_from_request(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "").strip()


@lru_cache(maxsize=1)
def _chat_service() -> ChatService:
    settings = get_settings()
    return ChatService(
        api_key=settings.nvidia_api_key or settings.ai_api_key,
        model=settings.nvidia_chat_model,
        base_url=settings.ai_base_url,
    )


@lru_cache(maxsize=1)
def _image_service() -> ImageGenerationService:
    settings = get_settings()
    return ImageGenerationService(
        api_key=settings.image_api_key or settings.nvidia_api_key or settings.ai_api_key,
        model=settings.image_model,
        base_url=settings.ai_base_url,
    )


@lru_cache(maxsize=1)
def _tts_service() -> TextToSpeechService:
    settings = get_settings()
    return TextToSpeechService(
        api_key=settings.tts_api_key or settings.nvidia_api_key or settings.ai_api_key,
        function_id=settings.tts_function_id,
    )


def _decode_base64_image(raw_image: str) -> bytes:
    value = raw_image.strip()
    if value.startswith("data:"):
        comma = value.find(",")
        value = value[comma + 1 :] if comma >= 0 else ""

    compact = "".join(value.split())
    if not compact:
        raise BackendError("Invalid base64 image payload.", status_code=400)

    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BackendError("Invalid base64 image payload.", status_code=400) from exc


def _decode_base64_text_file(raw_file: str) -> str:
    value = raw_file.strip()
    if value.startswith("data:"):
        comma = value.find(",")
        value = value[comma + 1 :] if comma >= 0 else ""
    compact = "".join(value.split())
    if not compact:
        raise BackendError("Invalid base64 code file payload.", status_code=400)
    try:
        payload = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BackendError("Invalid base64 code file payload.", status_code=400) from exc

    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            decoded = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = decoded.strip()
        if text:
            return text
    raise BackendError("Uploaded code file must be plain text.", status_code=400)


def _is_debug_request(text: str) -> bool:
    return bool(DEBUG_INTENT_PATTERN.search(text or ""))


def _code_filename_for_lang(lang: str) -> str:
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
    return mapping.get((lang or "").strip().lower(), "output.txt")


def _guess_code_language(code: str) -> str:
    sample = (code or "").strip().lower()
    if not sample:
        return ""
    if sample.startswith("<!doctype html") or "<html" in sample:
        return "html"
    if "def " in sample or "import " in sample or "print(" in sample:
        return "python"
    if "console.log" in sample or "const " in sample or "function " in sample:
        return "javascript"
    if "#include" in sample or "int main(" in sample:
        return "cpp"
    if "public class " in sample:
        return "java"
    if "package main" in sample or "fmt." in sample:
        return "go"
    if "fn main(" in sample:
        return "rust"
    if "select " in sample or "insert into " in sample:
        return "sql"
    return ""


def _extract_code_and_lang(text: str) -> tuple[str, str]:
    match = CODE_FENCE_PATTERN.search(text or "")
    if match:
        lang = (match.group("lang") or "").strip().lower()
        code = (match.group("code") or "").strip()
        if code:
            return code, (lang or _guess_code_language(code))
    raw = (text or "").strip()
    return raw, _guess_code_language(raw)


def _summary_for_very_long_code(code: str, file_name: str) -> str:
    snippet = code[:1200].rstrip()
    return (
        f"Code output is very long. The full version is attached as {file_name}.\n\n"
        "Starter snippet:\n\n"
        f"```text\n{snippet}\n```"
    )


def _build_code_attachment_payload(output: str) -> dict[str, str] | None:
    code, lang = _extract_code_and_lang(output)
    if not code:
        return None
    if len(code) < 2200:
        return None
    return {
        "code_file_name": _code_filename_for_lang(lang),
        "code_file_base64": base64.b64encode(code.encode("utf-8")).decode("utf-8"),
        "code_content": code,
    }


async def _run_text_mode_completion(
    message: str,
    mode: TextMode,
    prompt_type: str | None = None,
    code_file_name: str | None = None,
    code_file_base64: str | None = None,
) -> str:
    settings = get_settings()
    default_api_key = (settings.nvidia_api_key or settings.ai_api_key or "").strip()
    if not default_api_key:
        raise _safe_service_error(status_code=503)

    service_mode: Literal["chat", "code", "research", "prompt"] = (
        "prompt" if mode == "prompt" else "research" if mode in {"research", "deep_analysis"} else mode
    )
    request_message = _compose_prompt_request(prompt_type or "general", message) if mode == "prompt" else message
    model_override = settings.code_model if mode == "code" else settings.nvidia_chat_model
    effective_api_key = default_api_key
    thinking = False

    if mode == "deep_analysis":
        deepseek_api_key = (settings.deepseek_api_key or default_api_key or "").strip()
        effective_api_key = deepseek_api_key or default_api_key
        if settings.deepseek_model.strip():
            model_override = settings.deepseek_model
        thinking = True
        request_message = (
            "Deep analysis mode.\n"
            "Use careful, stepwise reasoning and include tradeoffs where relevant.\n\n"
            f"{message}"
        )

    if mode == "code":
        uploaded_code: str | None = None
        if code_file_base64:
            uploaded_code = _decode_base64_text_file(code_file_base64)

        if _is_debug_request(message) and not uploaded_code:
            return "For debug/fix requests, upload or provide the code file first."

        if uploaded_code:
            resolved_name = (code_file_name or "uploaded_code.txt").strip() or "uploaded_code.txt"
            if len(uploaded_code) > 70_000:
                uploaded_code = uploaded_code[:70_000].rstrip() + "\n...[truncated for analysis]"
            request_message = (
                f"User request:\n{message}\n\n"
                f"Uploaded file: {resolved_name}\n\n"
                "Use this file as the primary source.\n"
                "Return the full corrected or generated result as one complete file by default.\n\n"
                f"```text\n{uploaded_code}\n```"
            )

    try:
        return await _chat_service().generate_reply(
            request_message,
            history=[],
            mode=service_mode,
            model_override=model_override,
            api_key_override=effective_api_key,
            thinking=thinking,
        )
    except AIServiceError as exc:
        logger.warning("Text completion failed mode=%s", mode, exc_info=True)
        raise _safe_service_error() from exc


async def _describe_image_with_vision(message: str, image_base64: str) -> str:
    settings = get_settings()
    kimi_api_key = (settings.kimi_api_key or settings.ai_api_key or "").strip()
    if not kimi_api_key:
        raise _safe_service_error(status_code=503)
    image_bytes = _decode_base64_image(image_base64)

    try:
        return await _chat_service().generate_reply_with_image(
            message.strip() or "Describe this image.",
            image_bytes,
            mode="image_describe",
            model_override=settings.kimi_model,
            api_key_override=kimi_api_key,
            thinking=False,
        )
    except AIServiceError as exc:
        logger.warning("Vision completion failed.", exc_info=True)
        raise _safe_service_error() from exc


async def _generate_image(prompt: str, size: str, ratio: Literal["1:1", "16:9", "9:16"]) -> dict[str, str]:
    try:
        generated = await _image_service().generate_image(prompt, size=size, ratio=ratio)
        if generated.image_bytes:
            return {"image_base64": base64.b64encode(generated.image_bytes).decode("utf-8")}
        if generated.image_url:
            return {"image_url": generated.image_url}
        raise AIServiceError(SAFE_SERVICE_UNAVAILABLE_MESSAGE)
    except AIServiceError as exc:
        logger.warning("Image generation failed.", exc_info=True)
        raise _safe_service_error() from exc


async def _generate_tts(
    *,
    text: str,
    language: str,
    voice: str,
    emotion: str,
) -> dict[str, str]:
    try:
        generated = await _tts_service().generate_speech(
            text=text,
            language=language,
            voice=voice,
            emotion=emotion,
        )
        return {
            "audio_base64": base64.b64encode(generated.audio_bytes).decode("utf-8"),
            "audio_mime_type": generated.mime_type,
            "audio_file_name": f"jo_ai_tts.{generated.file_extension}",
        }
    except AIServiceError as exc:
        logger.warning("Text-to-speech generation failed.", exc_info=True)
        raise _safe_service_error() from exc


def _get_bot_runtime() -> BotRuntime | None:
    runtime = getattr(app.state, "bot_runtime", None)
    return runtime if isinstance(runtime, BotRuntime) else None


def _uptime_seconds() -> float:
    started_at = getattr(app.state, "started_at", None)
    if not isinstance(started_at, (int, float)):
        return 0.0
    return max(0.0, time.time() - float(started_at))


def _runtime_info_payload() -> dict[str, Any]:
    return build_runtime_info(version=VERSION, web_version=WEB_VERSION)


def _normalize_tracking_text(value: Any, max_len: int = 128) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:max_len]


def _append_debug_error(existing: str | None, message: str) -> str:
    if existing:
        return f"{existing} | {message}"
    return message


def _parse_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_telegram_user_from_init_data(raw_value: str | None) -> dict[str, Any]:
    raw = str(raw_value or "").strip()
    if not raw:
        return {}
    try:
        parsed = parse_qs(raw, keep_blank_values=False)
    except Exception:
        return {}
    user_entries = parsed.get("user")
    if not user_entries:
        return {}
    try:
        user_data = json.loads(user_entries[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return user_data if isinstance(user_data, dict) else {}


def _resolve_tracking_identity(request: Request, payload: TrackingRequestBase | None = None) -> TrackingIdentity | None:
    telegram_id = _parse_positive_int(getattr(payload, "telegram_id", None))
    username = _normalize_tracking_text(getattr(payload, "username", None))
    first_name = _normalize_tracking_text(getattr(payload, "first_name", None))
    last_name = _normalize_tracking_text(getattr(payload, "last_name", None))

    if telegram_id is None:
        telegram_id = _parse_positive_int(request.headers.get("x-telegram-id"))
    if telegram_id is None:
        telegram_id = _parse_positive_int(request.headers.get("x-telegram-user-id"))
    if telegram_id is None:
        telegram_id = _parse_positive_int(request.query_params.get("telegram_id"))

    if not username:
        username = _normalize_tracking_text(request.headers.get("x-telegram-username"))
    if not first_name:
        first_name = _normalize_tracking_text(request.headers.get("x-telegram-first-name"))
    if not last_name:
        last_name = _normalize_tracking_text(request.headers.get("x-telegram-last-name"))

    init_data = request.headers.get("x-telegram-init-data", "")
    if not init_data:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("tma "):
            init_data = auth_header[4:].strip()
    if not init_data:
        init_data = request.query_params.get("telegram_init_data", "")

    init_user = _parse_telegram_user_from_init_data(init_data)
    if telegram_id is None:
        telegram_id = _parse_positive_int(init_user.get("id"))
    if not username:
        username = _normalize_tracking_text(init_user.get("username"))
    if not first_name:
        first_name = _normalize_tracking_text(init_user.get("first_name"))
    if not last_name:
        last_name = _normalize_tracking_text(init_user.get("last_name"))

    if telegram_id is None:
        logger.warning(
            "Tracking identity missing | path=%s has_init_data=%s",
            request.url.path,
            bool(init_data),
        )
        return None

    return TrackingIdentity(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )


@lru_cache(maxsize=1)
def _tracking_service() -> SupabaseTrackingService:
    service = SupabaseTrackingService(get_settings())
    if service.enabled:
        logger.info("SUPABASE CONFIG LOADED | enabled=%s backend=%s", service.enabled, service.backend)
    else:
        logger.warning(
            "SUPABASE CONFIG INVALID | enabled=%s backend=%s reason=%s",
            service.enabled,
            service.backend,
            service.disabled_reason or "unknown",
        )
    return service


def _text_model_used(mode: TextMode) -> str:
    settings = get_settings()
    if mode == "code":
        return settings.code_model
    if mode == "deep_analysis" and (settings.deepseek_api_key or "").strip():
        return settings.deepseek_model
    return settings.nvidia_chat_model


async def _track_api_action(
    *,
    identity: TrackingIdentity | None,
    message_type: str,
    user_message: str,
    bot_reply: str | None,
    model_used: str | None,
    success: bool,
    message_increment: int = 0,
    image_increment: int = 0,
) -> None:
    if identity is None:
        logger.warning("TRACKING FAILED user=unknown message_type=%s error=missing telegram identity", message_type)
        return

    service = _tracking_service()
    if not service.enabled:
        logger.warning(
            "TRACKING FAILED user=%s message_type=%s error=tracking disabled reason=%s",
            identity.telegram_id,
            message_type,
            service.disabled_reason or "unknown",
        )
        return

    tracking_timeout_seconds = 4.0
    try:
        await asyncio.wait_for(
            service.track_action(
                identity=identity,
                message_type=message_type,
                user_message=user_message,
                bot_reply=bot_reply,
                model_used=model_used,
                success=success,
                message_increment=message_increment,
                image_increment=image_increment,
            ),
            timeout=tracking_timeout_seconds,
        )
        logger.info("TRACKING COMPLETE user=%s message_type=%s", identity.telegram_id, message_type)
    except asyncio.TimeoutError:
        logger.warning(
            "TRACKING FAILED user=%s message_type=%s error=timeout_after_%ss",
            identity.telegram_id,
            message_type,
            tracking_timeout_seconds,
        )
    except Exception as exc:
        logger.exception(
            "TRACKING FAILED user=%s message_type=%s error=%s",
            identity.telegram_id,
            message_type,
            exc,
        )


app = FastAPI(
    title="JO AI Service",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.bot_runtime = None
app.state.telegram_startup_task = None
app.state.started_at = time.time()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins_from_env(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _response_headers_middleware(request: Request, call_next):
    path = request.url.path
    request_id = (
        _normalize_tracking_text(request.headers.get("x-request-id"), max_len=64)
        or _normalize_tracking_text(request.headers.get("x-correlation-id"), max_len=64)
        or uuid.uuid4().hex
    )
    request.state.request_id = request_id

    start = time.perf_counter()
    should_log = _is_observable_request_path(path)
    if should_log:
        logger.info(
            "API REQUEST START | request_id=%s method=%s path=%s query=%s user_agent=%s",
            request_id,
            request.method,
            path,
            str(request.url.query or "").strip(),
            _normalize_tracking_text(request.headers.get("user-agent"), max_len=180) or "unknown",
        )

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "API REQUEST FAILED | request_id=%s method=%s path=%s duration_ms=%s error=%s",
            request_id,
            request.method,
            path,
            duration_ms,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": SAFE_SERVICE_UNAVAILABLE_MESSAGE,
                "request_id": request_id,
            },
        )

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Request-ID", request_id)
    if should_log:
        logger.info(
            "API REQUEST COMPLETE | request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            path,
            response.status_code,
            duration_ms,
        )
    return response


async def _process_webhook_update(runtime: BotRuntime, update: Update) -> None:
    try:
        await process_telegram_update(runtime, update)
    except Exception:
        logger.exception("Failed to process Telegram webhook update.")


@app.on_event("startup")
async def _startup() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    for warning in settings.validation_warnings:
        logger.warning("CONFIG WARNING | %s", warning)
    settings.require_valid()

    role = _read_env("PROCESS_ROLE") or "web"
    app.state.started_at = time.time()
    supabase_http_config = build_supabase_config(settings)
    key_type = supabase_http_config.key_type if supabase_http_config else "none"
    raw_service_role_env_set = bool(_read_env("SUPABASE_SERVICE_ROLE_KEY") or _read_env("SUPABASE_SECRET_KEY"))
    raw_anon_env_set = bool(_read_env("SUPABASE_ANON_KEY") or _read_env("SUPABASE_PUBLISHABLE_KEY"))
    logger.info("API STARTED | version=%s", VERSION)
    logger.info("PROCESS=%s ENTRYPOINT=main.py VERSION=%s", role, VERSION)
    logger.info(
        "SUPABASE CONFIG LOADED | supabase_url_set=%s service_role_set=%s anon_key_set=%s supabase_db_url_set=%s users_table=%s history_table=%s",
        bool(settings.supabase_url),
        bool(settings.supabase_service_role_key),
        bool(settings.supabase_anon_key),
        bool(settings.supabase_db_url),
        settings.supabase_users_table,
        settings.supabase_history_table,
    )
    logger.info(
        "SUPABASE KEY TYPE | key_type=%s allow_anon_fallback=%s raw_service_role_env_set=%s raw_anon_env_set=%s",
        key_type,
        settings.supabase_allow_anon_fallback,
        raw_service_role_env_set,
        raw_anon_env_set,
    )
    tracking_service = _tracking_service()
    logger.info(
        "TRACKING BACKEND SELECTED | enabled=%s backend=%s",
        tracking_service.enabled,
        tracking_service.backend,
    )
    if tracking_service.enabled:
        try:
            startup_check_ok = await asyncio.wait_for(tracking_service.verify_connection(), timeout=5.0)
            logger.info(
                "SUPABASE CONNECTION VERIFY RESULT | ok=%s backend=%s",
                startup_check_ok,
                tracking_service.backend,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "SUPABASE CONNECTION VERIFY FAILED | backend=%s error=startup_timeout",
                tracking_service.backend,
            )
    else:
        logger.warning(
            "SUPABASE CONFIG INVALID | reason=%s",
            tracking_service.disabled_reason or "no active tracking backend",
        )

    runtime = await create_bot_runtime()
    app.state.bot_runtime = runtime
    app.state.telegram_startup_task = start_telegram_startup_tasks(runtime)


@app.on_event("shutdown")
async def _shutdown() -> None:
    telegram_startup_task = getattr(app.state, "telegram_startup_task", None)
    if isinstance(telegram_startup_task, asyncio.Task):
        telegram_startup_task.cancel()
        with suppress(asyncio.CancelledError):
            await telegram_startup_task
    app.state.telegram_startup_task = None

    runtime = _get_bot_runtime()
    if runtime is None:
        return
    await close_bot_runtime(runtime)
    app.state.bot_runtime = None


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    message = first_error.get("msg", "Invalid request payload.")
    request_id = _request_id_from_request(request)
    logger.warning(
        "API REQUEST VALIDATION FAILED | request_id=%s method=%s path=%s error=%s",
        request_id or "unknown",
        request.method,
        request.url.path,
        message,
    )
    payload: dict[str, Any] = {"error": message}
    if request_id:
        payload["request_id"] = request_id
    return JSONResponse(status_code=422, content=payload)


@app.get("/")
def root() -> dict[str, Any]:
    payload = build_safe_version_summary(bot_version=VERSION, web_version=WEB_VERSION)
    payload["service"] = "JO AI"
    return payload


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    return _runtime_info_payload()


@app.get("/uptime")
@app.get("/api/uptime")
def uptime() -> dict[str, Any]:
    payload = build_safe_version_summary(bot_version=VERSION, web_version=WEB_VERSION)
    payload["uptime_seconds"] = round(_uptime_seconds(), 2)
    return payload


@app.get("/runtime-info")
@app.get("/api/runtime-info")
def runtime_info() -> dict[str, Any]:
    return _runtime_info_payload()


@app.get("/debug/supabase-test")
async def debug_supabase_test() -> JSONResponse:
    settings = get_settings()
    supabase_http_config = build_supabase_config(settings)
    tracking_service = _tracking_service()

    raw_env_presence = {
        "SUPABASE_URL": bool(_read_env("SUPABASE_URL")),
        "SUPABASE_PROJECT_URL": bool(_read_env("SUPABASE_PROJECT_URL")),
        "SUPABASE_SERVICE_ROLE_KEY": bool(_read_env("SUPABASE_SERVICE_ROLE_KEY")),
        "SUPABASE_SECRET_KEY": bool(_read_env("SUPABASE_SECRET_KEY")),
        "SUPABASE_ANON_KEY": bool(_read_env("SUPABASE_ANON_KEY")),
        "SUPABASE_PUBLISHABLE_KEY": bool(_read_env("SUPABASE_PUBLISHABLE_KEY")),
        "SUPABASE_ALLOW_ANON_FALLBACK": bool(_read_env("SUPABASE_ALLOW_ANON_FALLBACK")),
        "SUPABASE_DB_URL": bool(_read_env("SUPABASE_DB_URL")),
        "SUPABASE_DIRECT_CONNECTION_STRING": bool(_read_env("SUPABASE_DIRECT_CONNECTION_STRING")),
    }
    effective_env_presence = {
        "SUPABASE_URL": bool(settings.supabase_url),
        "SUPABASE_SERVICE_ROLE_KEY": bool(settings.supabase_service_role_key),
        "SUPABASE_ANON_KEY": bool(settings.supabase_anon_key),
        "SUPABASE_ALLOW_ANON_FALLBACK": bool(settings.supabase_allow_anon_fallback),
        "SUPABASE_DB_URL": bool(settings.supabase_db_url),
    }
    effective_url_present = effective_env_presence["SUPABASE_URL"]
    effective_service_role_present = effective_env_presence["SUPABASE_SERVICE_ROLE_KEY"]
    effective_anon_present = effective_env_presence["SUPABASE_ANON_KEY"]
    raw_allow_anon_fallback_value = _read_env("SUPABASE_ALLOW_ANON_FALLBACK").lower()
    raw_allow_anon_fallback_effective = raw_allow_anon_fallback_value in {"1", "true", "yes", "on"}
    env_loaded_correctly = {
        "SUPABASE_URL": effective_url_present
        == bool(raw_env_presence["SUPABASE_URL"] or raw_env_presence["SUPABASE_PROJECT_URL"]),
        "SUPABASE_SERVICE_ROLE_KEY": effective_service_role_present
        == bool(raw_env_presence["SUPABASE_SERVICE_ROLE_KEY"] or raw_env_presence["SUPABASE_SECRET_KEY"]),
        "SUPABASE_ANON_KEY": effective_anon_present
        == bool(raw_env_presence["SUPABASE_ANON_KEY"] or raw_env_presence["SUPABASE_PUBLISHABLE_KEY"]),
        "SUPABASE_ALLOW_ANON_FALLBACK": settings.supabase_allow_anon_fallback == raw_allow_anon_fallback_effective,
        "SUPABASE_DB_URL": effective_env_presence["SUPABASE_DB_URL"]
        == bool(raw_env_presence["SUPABASE_DB_URL"] or raw_env_presence["SUPABASE_DIRECT_CONNECTION_STRING"]),
    }

    configured_users_table = (settings.supabase_users_table or "").strip() or "users"
    configured_history_table = (settings.supabase_history_table or "").strip() or "history"
    expected_users_table = "users"
    expected_history_table = "history"
    table_names_match_expected = (
        configured_users_table == expected_users_table and configured_history_table == expected_history_table
    )

    logger.warning("SUPABASE DEBUG TEST START")
    logger.warning("SUPABASE DEBUG TEST ENV RAW PRESENCE | %s", raw_env_presence)
    logger.warning("SUPABASE DEBUG TEST ENV EFFECTIVE PRESENCE | %s", effective_env_presence)
    logger.warning("SUPABASE DEBUG TEST ENV LOADED CORRECTLY | %s", env_loaded_correctly)
    logger.warning(
        "SUPABASE DEBUG TEST TABLE CHECK | configured_users_table=%s configured_history_table=%s match_expected=%s",
        configured_users_table,
        configured_history_table,
        table_names_match_expected,
    )
    logger.warning(
        "SUPABASE DEBUG TEST TRACKING BACKEND | backend=%s enabled=%s disabled_reason=%s",
        tracking_service.backend,
        tracking_service.enabled,
        tracking_service.disabled_reason,
    )
    logger.warning(
        "SUPABASE DEBUG TEST KEY POLICY | selected_key_type=%s allow_anon_fallback=%s",
        supabase_http_config.key_type if supabase_http_config else "none",
        settings.supabase_allow_anon_fallback,
    )

    result: dict[str, Any] = {
        "supabase_client_initialized": False,
        "users_upsert_succeeded": False,
        "history_insert_succeeded": False,
        "error": None,
        "effective_key_type": supabase_http_config.key_type if supabase_http_config else "none",
        "effective_supabase_url": supabase_http_config.url if supabase_http_config else settings.supabase_url,
        "effective_tables": {
            "users": configured_users_table,
            "history": configured_history_table,
        },
        "expected_tables": {
            "users": "public.users",
            "history": "public.history",
        },
        "table_names_match_expected": table_names_match_expected,
        "env_presence_raw": raw_env_presence,
        "env_presence_effective": effective_env_presence,
        "env_loaded_correctly": env_loaded_correctly,
        "supabase_allow_anon_fallback": settings.supabase_allow_anon_fallback,
        "tracking_backend": tracking_service.backend,
        "tracking_enabled": tracking_service.enabled,
        "tracking_disabled_reason": tracking_service.disabled_reason,
    }

    if supabase_http_config is None:
        error_message = (
            "No effective Supabase HTTP write config selected. "
            "Set SUPABASE_SERVICE_ROLE_KEY, or explicitly enable SUPABASE_ALLOW_ANON_FALLBACK=true."
        )
        logger.error("SUPABASE DEBUG TEST CLIENT INIT FAILED | %s", error_message)
        result["error"] = _append_debug_error(result["error"], error_message)
        return JSONResponse(status_code=200, content=result)

    try:
        logger.warning(
            "SUPABASE DEBUG TEST CLIENT INIT START | url_present=%s key_type=%s allow_anon_fallback=%s",
            bool(supabase_http_config.url),
            supabase_http_config.key_type,
            settings.supabase_allow_anon_fallback,
        )
        client = create_client(supabase_http_config.url, supabase_http_config.api_key)
        result["supabase_client_initialized"] = True
        logger.warning("SUPABASE DEBUG TEST CLIENT INIT SUCCESS")
    except Exception as exc:
        error_message = f"Supabase client init failed: {exc}"
        logger.exception("SUPABASE DEBUG TEST CLIENT INIT FAILED | error=%s", exc)
        result["error"] = _append_debug_error(result["error"], error_message)
        return JSONResponse(status_code=200, content=result)

    debug_telegram_id = int(time.time()) + 9_000_000_000
    now_iso = datetime.now(timezone.utc).isoformat()
    user_payload = {
        "telegram_id": debug_telegram_id,
        "username": "debug_supabase_user",
        "first_name": "Debug",
        "last_name": "SupabaseTest",
        "last_seen_at": now_iso,
        "total_messages": 1,
        "total_images": 0,
    }
    history_payload = {
        "telegram_id": debug_telegram_id,
        "message_type": "debug_supabase_test",
        "user_message": "debug users/history insert proof test",
        "bot_reply": "debug endpoint wrote this row",
        "model_used": "debug-endpoint",
        "success": True,
        "created_at": now_iso,
    }
    result["column_names_used"] = {
        "users": sorted(user_payload.keys()),
        "history": sorted(history_payload.keys()),
    }

    logger.warning(
        "SUPABASE DEBUG TEST USERS UPSERT START | table=public.%s telegram_id=%s",
        expected_users_table,
        debug_telegram_id,
    )
    try:
        users_response = client.table(expected_users_table).upsert(
            user_payload,
            on_conflict="telegram_id",
            returning="representation",
            count="exact",
        ).execute()
        users_data = getattr(users_response, "data", None)
        users_ok = bool(users_data)
        result["users_upsert_succeeded"] = users_ok
        if users_ok:
            logger.warning("SUPABASE DEBUG TEST USERS UPSERT SUCCESS | telegram_id=%s", debug_telegram_id)
        else:
            error_message = "Users upsert executed but returned no rows."
            logger.error("SUPABASE DEBUG TEST USERS UPSERT FAILED | %s", error_message)
            result["error"] = _append_debug_error(result["error"], error_message)
    except Exception as exc:
        error_message = f"Users upsert failed: {exc}"
        logger.exception("SUPABASE DEBUG TEST USERS UPSERT FAILED | error=%s", exc)
        result["error"] = _append_debug_error(result["error"], error_message)

    logger.warning(
        "SUPABASE DEBUG TEST HISTORY INSERT START | table=public.%s telegram_id=%s",
        expected_history_table,
        debug_telegram_id,
    )
    try:
        history_response = client.table(expected_history_table).insert(
            history_payload,
            returning="representation",
            count="exact",
        ).execute()
        history_data = getattr(history_response, "data", None)
        history_ok = bool(history_data)
        result["history_insert_succeeded"] = history_ok
        if history_ok:
            logger.warning("SUPABASE DEBUG TEST HISTORY INSERT SUCCESS | telegram_id=%s", debug_telegram_id)
        else:
            error_message = "History insert executed but returned no rows."
            logger.error("SUPABASE DEBUG TEST HISTORY INSERT FAILED | %s", error_message)
            result["error"] = _append_debug_error(result["error"], error_message)
    except Exception as exc:
        error_message = f"History insert failed: {exc}"
        logger.exception("SUPABASE DEBUG TEST HISTORY INSERT FAILED | error=%s", exc)
        result["error"] = _append_debug_error(result["error"], error_message)

    logger.warning(
        "SUPABASE DEBUG TEST DONE | client_initialized=%s users_ok=%s history_ok=%s error_present=%s",
        result["supabase_client_initialized"],
        result["users_upsert_succeeded"],
        result["history_insert_succeeded"],
        bool(result["error"]),
    )
    return JSONResponse(status_code=200, content=result)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    runtime = _get_bot_runtime()
    if runtime is None:
        return JSONResponse(status_code=503, content={"error": "Bot runtime is not ready."})

    if runtime.telegram_webhook_secret:
        received_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
        if received_secret != runtime.telegram_webhook_secret:
            return JSONResponse(status_code=403, content={"error": "Invalid webhook secret."})

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    try:
        update = Update.model_validate(payload, context={"bot": runtime.bot})
    except ValidationError:
        return JSONResponse(status_code=400, content={"error": "Invalid Telegram update payload."})

    asyncio.create_task(_process_webhook_update(runtime, update))
    return JSONResponse(status_code=200, content={"ok": True})


async def _handle_text_mode_request(
    *,
    request: Request,
    mode: TextMode,
    message: str,
    prompt_type: str | None = None,
    code_file_name: str | None = None,
    code_file_base64: str | None = None,
    identity: TrackingIdentity | None = None,
) -> JSONResponse:
    request_id = _request_id_from_request(request)
    user_id = identity.telegram_id if identity else "unknown"
    logger.info(
        "API MODE START | request_id=%s mode=%s user=%s message_len=%s",
        request_id or "unknown",
        mode,
        user_id,
        len(message or ""),
    )

    refusal = _maybe_block_sensitive_request(message, prompt_type)
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type=mode,
            user_message=message,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=_text_model_used(mode),
            success=False,
            message_increment=1,
        )
        logger.info(
            "API MODE REFUSED | request_id=%s mode=%s user=%s",
            request_id or "unknown",
            mode,
            user_id,
        )
        return refusal
    try:
        output = await _run_text_mode_completion(
            message,
            mode=mode,
            prompt_type=prompt_type,
            code_file_name=code_file_name,
            code_file_base64=code_file_base64,
        )
        payload: dict[str, Any] = {"output": output}

        if mode == "code":
            attachment = _build_code_attachment_payload(output)
            if attachment:
                payload["code_file_name"] = attachment["code_file_name"]
                payload["code_file_base64"] = attachment["code_file_base64"]
                code_content = attachment.get("code_content", "")
                if isinstance(code_content, str) and len(code_content) >= 16_000:
                    payload["output"] = _summary_for_very_long_code(code_content, attachment["code_file_name"])
                    payload["warning"] = "Full code is attached as a file."
        await _track_api_action(
            identity=identity,
            message_type=mode,
            user_message=message,
            bot_reply=str(payload.get("output", output)),
            model_used=_text_model_used(mode),
            success=True,
            message_increment=1,
        )
        logger.info(
            "API MODE SUCCESS | request_id=%s mode=%s user=%s output_len=%s",
            request_id or "unknown",
            mode,
            user_id,
            len(str(payload.get("output", output) or "")),
        )
        return JSONResponse(status_code=200, content=payload)
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type=mode,
            user_message=message,
            bot_reply=exc.message,
            model_used=_text_model_used(mode),
            success=False,
            message_increment=1,
        )
        logger.warning(
            "API MODE BACKEND ERROR | request_id=%s mode=%s user=%s status=%s error=%s",
            request_id or "unknown",
            mode,
            user_id,
            exc.status_code,
            exc.message,
        )
        payload = {"error": exc.message}
        if request_id:
            payload["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload)
    except Exception as exc:
        logger.exception(
            "API MODE FAILED | request_id=%s mode=%s user=%s error=%s",
            request_id or "unknown",
            mode,
            user_id,
            exc,
        )
        raise


@app.post("/ai")
@app.post("/api/ai")
async def ai_endpoint(request: Request, payload: AITextRequest) -> JSONResponse:
    identity = _resolve_tracking_identity(request, payload)
    return await _handle_text_mode_request(
        request=request,
        mode=payload.mode,
        message=payload.message,
        prompt_type=payload.prompt_type,
        code_file_name=payload.code_file_name,
        code_file_base64=payload.code_file_base64,
        identity=identity,
    )


@app.post("/chat")
@app.post("/api/chat")
async def chat_endpoint(request: Request, payload: ChatRequest) -> JSONResponse:
    identity = _resolve_tracking_identity(request, payload)
    return await _handle_text_mode_request(request=request, mode="chat", message=payload.message, identity=identity)


@app.post("/code")
@app.post("/api/code")
async def code_endpoint(request: Request, payload: CodeRequest) -> JSONResponse:
    identity = _resolve_tracking_identity(request, payload)
    return await _handle_text_mode_request(
        request=request,
        mode="code",
        message=payload.message,
        code_file_name=payload.code_file_name,
        code_file_base64=payload.code_file_base64,
        identity=identity,
    )


@app.post("/research")
@app.post("/api/research")
async def research_endpoint(request: Request, payload: ChatRequest) -> JSONResponse:
    identity = _resolve_tracking_identity(request, payload)
    return await _handle_text_mode_request(request=request, mode="research", message=payload.message, identity=identity)


@app.post("/prompt")
@app.post("/api/prompt")
async def prompt_endpoint(request: Request, payload: PromptRequest) -> JSONResponse:
    identity = _resolve_tracking_identity(request, payload)
    return await _handle_text_mode_request(
        request=request,
        mode="prompt",
        message=payload.message,
        prompt_type=payload.effective_prompt_type,
        identity=identity,
    )


@app.post("/image")
@app.post("/api/image")
async def image_endpoint(request: Request, payload: ImageRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    user_prompt = payload.effective_prompt
    logger.info(
        "API IMAGE START | request_id=%s user=%s prompt_len=%s ratio=%s image_type=%s",
        request_id or "unknown",
        user_id,
        len(user_prompt or ""),
        payload.effective_ratio,
        payload.image_type or "",
    )
    refusal = _maybe_block_sensitive_request(payload.effective_prompt, payload.image_type, payload.ratio)
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=settings.image_model,
            success=False,
            image_increment=1,
        )
        logger.info(
            "API IMAGE REFUSED | request_id=%s user=%s",
            request_id or "unknown",
            user_id,
        )
        return refusal
    try:
        prompt = user_prompt
        style_hint = payload.effective_style_hint
        if style_hint:
            prompt = f"{prompt}\nStyle hints: {style_hint}"
        result_payload = await _generate_image(
            prompt=prompt,
            size=payload.effective_size,
            ratio=payload.effective_ratio,
        )
        response_payload: dict[str, Any] = {
            "output": "Image generated successfully.",
            "ratio": payload.effective_ratio,
        }
        response_payload.update(result_payload)
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=str(response_payload.get("output", "Image generated successfully.")),
            model_used=settings.image_model,
            success=True,
            image_increment=1,
        )
        logger.info(
            "API IMAGE SUCCESS | request_id=%s user=%s ratio=%s has_image_base64=%s has_image_url=%s",
            request_id or "unknown",
            user_id,
            payload.effective_ratio,
            "image_base64" in response_payload,
            "image_url" in response_payload,
        )
        return JSONResponse(status_code=200, content=response_payload)
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=exc.message,
            model_used=settings.image_model,
            success=False,
            image_increment=1,
        )
        logger.warning(
            "API IMAGE BACKEND ERROR | request_id=%s user=%s status=%s error=%s",
            request_id or "unknown",
            user_id,
            exc.status_code,
            exc.message,
        )
        payload_response = {"error": exc.message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload_response)
    except Exception as exc:
        logger.exception(
            "API IMAGE FAILED | request_id=%s user=%s error=%s",
            request_id or "unknown",
            user_id,
            exc,
        )
        raise


@app.post("/vision")
@app.post("/api/vision")
async def vision_endpoint(request: Request, payload: VisionDescribeRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    user_message = payload.effective_message
    logger.info(
        "API VISION START | request_id=%s user=%s message_len=%s image_base64_len=%s",
        request_id or "unknown",
        user_id,
        len(user_message or ""),
        len(payload.image_base64 or ""),
    )
    refusal = _maybe_block_sensitive_request(payload.effective_message)
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="vision",
            user_message=user_message,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=settings.kimi_model,
            success=False,
            message_increment=1,
        )
        logger.info(
            "API VISION REFUSED | request_id=%s user=%s",
            request_id or "unknown",
            user_id,
        )
        return refusal
    try:
        output = await _describe_image_with_vision(user_message, payload.image_base64)
        await _track_api_action(
            identity=identity,
            message_type="vision",
            user_message=user_message,
            bot_reply=output,
            model_used=settings.kimi_model,
            success=True,
            message_increment=1,
        )
        logger.info(
            "API VISION SUCCESS | request_id=%s user=%s output_len=%s",
            request_id or "unknown",
            user_id,
            len(output or ""),
        )
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="vision",
            user_message=user_message,
            bot_reply=exc.message,
            model_used=settings.kimi_model,
            success=False,
            message_increment=1,
        )
        logger.warning(
            "API VISION BACKEND ERROR | request_id=%s user=%s status=%s error=%s",
            request_id or "unknown",
            user_id,
            exc.status_code,
            exc.message,
        )
        payload_response = {"error": exc.message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload_response)
    except Exception as exc:
        logger.exception(
            "API VISION FAILED | request_id=%s user=%s error=%s",
            request_id or "unknown",
            user_id,
            exc,
        )
        raise


@app.post("/tts")
@app.post("/api/tts")
async def tts_endpoint(request: Request, payload: TTSRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    user_text = payload.effective_text
    logger.info(
        "API TTS START | request_id=%s user=%s text_len=%s language=%s voice=%s emotion=%s",
        request_id or "unknown",
        user_id,
        len(user_text or ""),
        payload.effective_language,
        payload.effective_voice,
        payload.effective_emotion,
    )
    refusal = _maybe_block_sensitive_request(
        payload.effective_text,
        payload.effective_language,
        payload.effective_voice,
        payload.effective_emotion,
    )
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="tts",
            user_message=user_text,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=settings.tts_function_id,
            success=False,
            message_increment=1,
        )
        logger.info(
            "API TTS REFUSED | request_id=%s user=%s",
            request_id or "unknown",
            user_id,
        )
        return refusal
    try:
        generated = await _generate_tts(
            text=user_text,
            language=payload.effective_language,
            voice=payload.effective_voice,
            emotion=payload.effective_emotion,
        )
        response_payload: dict[str, Any] = {
            "output": "Speech generated successfully.",
            "language": payload.effective_language,
            "voice": payload.effective_voice,
            "emotion": payload.effective_emotion,
        }
        response_payload.update(generated)
        await _track_api_action(
            identity=identity,
            message_type="tts",
            user_message=user_text,
            bot_reply=str(response_payload.get("output", "Speech generated successfully.")),
            model_used=settings.tts_function_id,
            success=True,
            message_increment=1,
        )
        logger.info(
            "API TTS SUCCESS | request_id=%s user=%s audio_mime_type=%s",
            request_id or "unknown",
            user_id,
            response_payload.get("audio_mime_type", ""),
        )
        return JSONResponse(status_code=200, content=response_payload)
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="tts",
            user_message=user_text,
            bot_reply=exc.message,
            model_used=settings.tts_function_id,
            success=False,
            message_increment=1,
        )
        logger.warning(
            "API TTS BACKEND ERROR | request_id=%s user=%s status=%s error=%s",
            request_id or "unknown",
            user_id,
            exc.status_code,
            exc.message,
        )
        payload_response = {"error": exc.message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload_response)
    except Exception as exc:
        logger.exception(
            "API TTS FAILED | request_id=%s user=%s error=%s",
            request_id or "unknown",
            user_id,
            exc,
        )
        raise


if __name__ == "__main__":
    host = _read_env("HOST") or "0.0.0.0"
    try:
        port = int(_read_env("PORT") or "8000")
    except ValueError:
        port = 8000
    uvicorn.run("main:app", host=host, port=port)
