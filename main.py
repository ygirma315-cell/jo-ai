from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import uuid
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, parse_qsl, urlparse

import aiohttp
import uvicorn
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.types import Update
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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
from bot.services.admin_service import SupabaseAdminService
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
from bot.services.supabase_client import build_supabase_config
from bot.services.tracking_service import SupabaseTrackingService, TrackingIdentity, TrackingMedia
from bot.security import (
    SAFE_INTERNAL_DETAILS_REFUSAL,
    SAFE_SERVICE_UNAVAILABLE_MESSAGE,
    build_safe_version_summary,
    guardrail_response_for_user_query,
)
from version import VERSION, WEB_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent
ADMIN_FRONTEND_DIR = PROJECT_ROOT / "admin"
MEDIA_ASSETS_DIR = PROJECT_ROOT / "media_assets"
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
GeminiMode = Literal["chat", "image", "video", "voice"]
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
IMAGE_ENDPOINT_TIMEOUT_SECONDS = 110
VIDEO_ASPECT_RATIOS = ("16:9", "9:16")
VIDEO_DEFAULT_ASPECT_RATIO = "16:9"
VIDEO_DEFAULT_DURATION_SECONDS = 4
VIDEO_ENDPOINT_TIMEOUT_SECONDS = 200
GPT_AUDIO_ENDPOINT_TIMEOUT_SECONDS = 120
GEMINI_TEMP_DISABLED = True

IMAGE_MODEL_LABEL_JO = "JO AI Image Generate"
IMAGE_MODEL_LABEL_CHAT_GBT = "Chat GBT"
IMAGE_MODEL_LABEL_GROK_IMAGINE = "Grok Imagine"
VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO = "Grok Text to Video"
GPT_AUDIO_MODEL_LABEL = "GPT Audio"

IMAGE_MODEL_OPTION_JO = "jo_ai_image_generate"
IMAGE_MODEL_OPTION_CHAT_GBT = "chat_gbt"
IMAGE_MODEL_OPTION_GROK_IMAGINE = "grok_imagine"
VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO = "grok_text_to_video"
VIDEO_JOIN_CHANNEL_USERNAME = "@JO_AI_CHAT_BOT"
VIDEO_JOIN_CHANNEL_URL = "https://t.me/JO_AI_CHAT_BOT"
VIDEO_ALLOWED_MEMBERSHIP_STATUSES = {"creator", "administrator", "member", "restricted"}

IMAGE_MODEL_OPTION_LABELS: dict[str, str] = {
    IMAGE_MODEL_OPTION_JO: IMAGE_MODEL_LABEL_JO,
    IMAGE_MODEL_OPTION_CHAT_GBT: IMAGE_MODEL_LABEL_CHAT_GBT,
    IMAGE_MODEL_OPTION_GROK_IMAGINE: IMAGE_MODEL_LABEL_GROK_IMAGINE,
}
IMAGE_MODEL_OPTION_ALIASES: dict[str, str] = {
    IMAGE_MODEL_OPTION_JO: IMAGE_MODEL_OPTION_JO,
    "jo_ai": IMAGE_MODEL_OPTION_JO,
    "jo ai image generate": IMAGE_MODEL_OPTION_JO,
    "image_generator": IMAGE_MODEL_OPTION_JO,
    "image generator": IMAGE_MODEL_OPTION_JO,
    IMAGE_MODEL_OPTION_CHAT_GBT: IMAGE_MODEL_OPTION_CHAT_GBT,
    "chat gbt": IMAGE_MODEL_OPTION_CHAT_GBT,
    "chatgbt": IMAGE_MODEL_OPTION_CHAT_GBT,
    "gpt_image_1_mini": IMAGE_MODEL_OPTION_CHAT_GBT,
    "gpt image 1 mini": IMAGE_MODEL_OPTION_CHAT_GBT,
    "gpt-image-1-mini": IMAGE_MODEL_OPTION_CHAT_GBT,
    IMAGE_MODEL_OPTION_GROK_IMAGINE: IMAGE_MODEL_OPTION_GROK_IMAGINE,
    "grok imagine": IMAGE_MODEL_OPTION_GROK_IMAGINE,
    "grok-imagine": IMAGE_MODEL_OPTION_GROK_IMAGINE,
}
VIDEO_MODEL_OPTION_LABELS: dict[str, str] = {
    VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO: VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO,
}
VIDEO_MODEL_OPTION_ALIASES: dict[str, str] = {
    VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO: VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO,
    "grok text to video": VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO,
    "grok-video": VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO,
    "grok video": VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO,
}
OBSERVABLE_REQUEST_PATHS = frozenset(
    {
        "/ai",
        "/chat",
        "/code",
        "/research",
        "/prompt",
        "/image",
        "/video",
        "/gpt-audio",
        "/vision",
        "/tts",
        "/telegram/webhook",
        "/debug/supabase-test",
    }
)
ADMIN_SESSION_TOKEN_TTL_SECONDS = 60 * 60 * 12
ADMIN_INIT_DATA_MAX_AGE_SECONDS = 60 * 60 * 24
ADMIN_SESSION_COOKIE_NAME = "jo_admin_session"
ADMIN_SESSION_COOKIE_SAMESITE = "lax"
ADMIN_SESSION_COOKIE_SECURE = True
KEEPALIVE_MIN_LOOP_SECONDS = 30
_ADMIN_SESSION_TOKENS: dict[str, dict[str, Any]] = {}


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
    ratio: Literal["1:1", "16:9", "9:16"] | None = Field(default=None)
    size: str | None = Field(default=None, pattern=r"^\d+x\d+$")
    model: str | None = Field(default=None, max_length=120)
    image_model: str | None = Field(default=None, max_length=120)

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


class GPTAudioRequest(TrackingRequestBase):
    prompt: str | None = Field(default=None, max_length=12000)
    message: str | None = Field(default=None, max_length=12000)

    @model_validator(mode="after")
    def _validate_prompt(self) -> "GPTAudioRequest":
        if not self.prompt and not self.message:
            raise ValueError("Either 'prompt' or 'message' must be provided.")
        return self

    @property
    def effective_prompt(self) -> str:
        return self.prompt or self.message or ""


class GeminiRequest(TrackingRequestBase):
    message: str = Field(min_length=1, max_length=32000)
    mode: GeminiMode | None = None
    model: str | None = Field(default=None, max_length=120)
    ratio: Literal["1:1", "16:9", "9:16"] | None = Field(default=None)
    size: str | None = Field(default=None, pattern=r"^\d+x\d+$")
    language: str | None = Field(default=None, max_length=16)
    voice: str | None = Field(default=None, max_length=32)
    emotion: str | None = Field(default=None, max_length=32)

    @property
    def effective_mode(self) -> GeminiMode:
        value = str(self.mode or "").strip().lower()
        if value in {"chat", "image", "video", "voice"}:
            return value  # type: ignore[return-value]
        return "chat"

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
    def effective_model_option(self) -> str:
        return _resolve_image_model_option(self.model)

    @property
    def effective_model_option(self) -> str:
        return _resolve_image_model_option(self.image_model or self.model)


class VideoRequest(TrackingRequestBase):
    prompt: str | None = Field(default=None, max_length=4000)
    message: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=120)
    video_model: str | None = Field(default=None, max_length=120)
    duration_seconds: int | None = Field(default=None, ge=1, le=10)
    duration: int | None = Field(default=None, ge=1, le=10)
    aspect_ratio: Literal["16:9", "9:16"] | None = Field(default=None)
    ratio: Literal["16:9", "9:16"] | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_prompt(self) -> "VideoRequest":
        if not self.prompt and not self.message:
            raise ValueError("Either 'prompt' or 'message' must be provided.")
        return self

    @property
    def effective_prompt(self) -> str:
        return self.prompt or self.message or ""

    @property
    def effective_model_option(self) -> str:
        return _resolve_video_model_option(self.video_model or self.model)

    @property
    def effective_duration_seconds(self) -> int:
        if isinstance(self.duration_seconds, int):
            return max(1, min(10, self.duration_seconds))
        if isinstance(self.duration, int):
            return max(1, min(10, self.duration))
        return VIDEO_DEFAULT_DURATION_SECONDS

    @property
    def effective_aspect_ratio(self) -> Literal["16:9", "9:16"]:
        candidate = self.aspect_ratio or self.ratio
        if candidate in VIDEO_ASPECT_RATIOS:
            return candidate
        return VIDEO_DEFAULT_ASPECT_RATIO  # type: ignore[return-value]


class ReferralClaimRequest(TrackingRequestBase):
    referral_code: str = Field(min_length=1, max_length=64)
    frontend_source: str | None = Field(default=None, max_length=40)


class EngagementConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    message_template: str | None = Field(default=None, max_length=400)
    inactivity_minutes: int | None = Field(default=None, ge=30, le=10_080)
    cooldown_minutes: int | None = Field(default=None, ge=30, le=43_200)
    batch_size: int | None = Field(default=None, ge=1, le=500)


class AdminTokenAuthRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


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


def _status_code_for_ai_error(message: str) -> int:
    lower = str(message or "").strip().lower()
    if not lower:
        return 503
    if "quota" in lower or "rate-limit" in lower or "rate limit" in lower:
        return 429
    if "invalid" in lower and "api key" in lower:
        return 401
    if "model is not available" in lower:
        return 400
    return 503


def _safe_guardrail_response(message: str) -> JSONResponse:
    safe_message = str(message or "").strip() or SAFE_INTERNAL_DETAILS_REFUSAL
    return JSONResponse(status_code=200, content={"output": safe_message})


def _maybe_block_sensitive_request(*parts: str | None) -> JSONResponse | None:
    guardrail_response = guardrail_response_for_user_query(*parts)
    if guardrail_response:
        return _safe_guardrail_response(guardrail_response)
    return None


def _normalize_model_option(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_image_model_option(value: str | None) -> str:
    normalized = _normalize_model_option(value)
    if not normalized:
        return IMAGE_MODEL_OPTION_JO
    return IMAGE_MODEL_OPTION_ALIASES.get(normalized, IMAGE_MODEL_OPTION_JO)


def _resolve_video_model_option(value: str | None) -> str:
    normalized = _normalize_model_option(value)
    if not normalized:
        return VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO
    return VIDEO_MODEL_OPTION_ALIASES.get(normalized, VIDEO_MODEL_OPTION_GROK_TEXT_TO_VIDEO)


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


def _extract_admin_token(request: Request) -> str:
    header_token = str(request.headers.get("x-admin-token") or "").strip()
    if header_token:
        return header_token

    auth_header = str(request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = str(request.cookies.get(ADMIN_SESSION_COOKIE_NAME) or "").strip()
    if cookie_token:
        return cookie_token
    return ""


def _prune_expired_admin_sessions(now_ts: float | None = None) -> None:
    now_value = now_ts if isinstance(now_ts, (int, float)) else time.time()
    expired_tokens = [
        token
        for token, payload in _ADMIN_SESSION_TOKENS.items()
        if float(payload.get("expires_at", 0.0) or 0.0) <= now_value
    ]
    for token in expired_tokens:
        _ADMIN_SESSION_TOKENS.pop(token, None)


def _issue_admin_session_token(telegram_id: int, *, auth_method: str) -> dict[str, Any]:
    now_ts = time.time()
    _prune_expired_admin_sessions(now_ts)
    token = secrets.token_urlsafe(32)
    expires_at = now_ts + ADMIN_SESSION_TOKEN_TTL_SECONDS
    _ADMIN_SESSION_TOKENS[token] = {
        "telegram_id": telegram_id,
        "auth_method": str(auth_method or "").strip() or "unknown",
        "issued_at": now_ts,
        "expires_at": expires_at,
    }
    return {
        "token": token,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "telegram_id": telegram_id,
        "auth_method": str(auth_method or "").strip() or "unknown",
        "ttl_seconds": ADMIN_SESSION_TOKEN_TTL_SECONDS,
    }


def _admin_session_payload(token: str) -> dict[str, Any] | None:
    candidate = str(token or "").strip()
    if not candidate:
        return None
    _prune_expired_admin_sessions()
    payload = _ADMIN_SESSION_TOKENS.get(candidate)
    if not isinstance(payload, dict):
        return None
    return payload


def _validate_admin_session_token(token: str) -> bool:
    return _admin_session_payload(token) is not None


def _set_admin_session_cookie(response: Response, token: str, request: Request | None = None) -> None:
    secure_cookie = ADMIN_SESSION_COOKIE_SECURE
    if request is not None and str(request.url.scheme or "").lower() != "https":
        secure_cookie = False
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        value=token,
        max_age=ADMIN_SESSION_TOKEN_TTL_SECONDS,
        expires=ADMIN_SESSION_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=secure_cookie,
        samesite=ADMIN_SESSION_COOKIE_SAMESITE,
        path="/",
    )


def _clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_SESSION_COOKIE_NAME, path="/")


def _extract_telegram_init_data(request: Request) -> str:
    init_data = str(request.headers.get("x-telegram-init-data") or "").strip()
    if init_data:
        return init_data

    auth_header = str(request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("tma "):
        return auth_header[4:].strip()

    return str(request.query_params.get("telegram_init_data") or "").strip()


def _validate_telegram_init_data(init_data: str, bot_token: str) -> dict[str, Any] | None:
    raw_init_data = str(init_data or "").strip()
    raw_bot_token = str(bot_token or "").strip()
    if not raw_init_data or not raw_bot_token:
        return None

    pairs = dict(parse_qsl(raw_init_data, keep_blank_values=True))
    provided_hash = str(pairs.pop("hash", "")).strip()
    if not provided_hash:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", raw_bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(computed_hash, provided_hash):
        return None

    auth_date = _parse_positive_int(pairs.get("auth_date"))
    if auth_date is None:
        return None
    now_ts = int(time.time())
    if abs(now_ts - auth_date) > ADMIN_INIT_DATA_MAX_AGE_SECONDS:
        return None

    raw_user = pairs.get("user")
    if not isinstance(raw_user, str) or not raw_user.strip():
        return None
    try:
        parsed_user = json.loads(raw_user)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed_user, dict):
        return None
    return parsed_user


def _validate_telegram_login_payload(payload: dict[str, Any], bot_token: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if not str(bot_token or "").strip():
        return None

    provided_hash = str(payload.get("hash") or "").strip()
    if not provided_hash:
        return None

    prepared: dict[str, str] = {}
    for key, value in payload.items():
        if key == "hash" or value is None:
            continue
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, bool):
            prepared[normalized_key] = "1" if value else "0"
        elif isinstance(value, (int, float)):
            prepared[normalized_key] = str(int(value))
        else:
            prepared[normalized_key] = str(value)
    if not prepared:
        return None

    auth_date = _parse_positive_int(prepared.get("auth_date"))
    if auth_date is None:
        return None
    now_ts = int(time.time())
    if abs(now_ts - auth_date) > ADMIN_INIT_DATA_MAX_AGE_SECONDS:
        return None

    data_check_string = "\n".join(f"{key}={prepared[key]}" for key in sorted(prepared))
    secret_key = hashlib.sha256(str(bot_token).encode("utf-8")).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(computed_hash, provided_hash):
        return None
    return prepared


def _resolve_admin_telegram_id_from_widget_payload(request: Request, payload: dict[str, Any]) -> int | None:
    settings = get_settings()
    verification_bot_token = settings.admin_dashboard_telegram_bot_token or settings.bot_token
    validated = _validate_telegram_login_payload(payload, verification_bot_token)
    if validated is None:
        logger.warning(
            "ADMIN TELEGRAM AUTH FAILED | request_id=%s reason=invalid_widget_payload",
            _request_id_from_request(request) or "unknown",
        )
        return None
    return _parse_positive_int(validated.get("id"))


def _resolve_admin_telegram_id(request: Request) -> int | None:
    settings = get_settings()
    init_data = _extract_telegram_init_data(request)
    if init_data:
        verification_bot_token = settings.admin_dashboard_telegram_bot_token or settings.bot_token
        validated_user = _validate_telegram_init_data(init_data, verification_bot_token)
        if validated_user is None:
            logger.warning(
                "ADMIN TELEGRAM AUTH FAILED | request_id=%s reason=invalid_init_data",
                _request_id_from_request(request) or "unknown",
            )
            return None
        return _parse_positive_int(validated_user.get("id"))

    client_host = str(request.client.host if request.client else "").strip().lower()
    if client_host in {"127.0.0.1", "::1", "localhost"}:
        fallback_id = _parse_positive_int(request.headers.get("x-telegram-id"))
        if fallback_id is None:
            fallback_id = _parse_positive_int(request.query_params.get("telegram_id"))
        return fallback_id
    return None


def _admin_owner_telegram_id() -> int | None:
    service = _admin_service()
    if service.enabled:
        resolved = service.resolve_admin_owner_telegram_id()
        if resolved:
            return int(resolved)
    settings = get_settings()
    if settings.admin_dashboard_owner_telegram_id:
        return int(settings.admin_dashboard_owner_telegram_id)
    fallback_allowlist = tuple(int(value) for value in settings.admin_dashboard_allowlist_telegram_ids if int(value) > 0)
    return int(fallback_allowlist[0]) if fallback_allowlist else None


def _admin_allowlist() -> tuple[int, ...]:
    owner_id = _admin_owner_telegram_id()
    return (int(owner_id),) if owner_id else ()


def _configured_admin_signin_token() -> str:
    return str(get_settings().admin_signin_token or "").strip()


def _validate_admin_signin_token(candidate: str) -> bool:
    expected = _configured_admin_signin_token()
    provided = str(candidate or "").strip()
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)


def _is_admin_allowlisted(telegram_id: int | None) -> bool:
    owner_id = _admin_owner_telegram_id()
    if not telegram_id or not owner_id:
        return False
    if int(telegram_id) != int(owner_id):
        return False

    service = _admin_service()
    if service.enabled and not service.is_known_telegram_user(int(telegram_id)):
        return False
    return True


def _require_admin_access(request: Request) -> None:
    provided = _extract_admin_token(request)
    if provided and _validate_admin_session_token(provided):
        return

    logger.warning(
        "ADMIN AUTH FAILED | path=%s request_id=%s",
        request.url.path,
        _request_id_from_request(request) or "unknown",
    )
    raise HTTPException(status_code=401, detail="Admin session is required. Login with Telegram or admin token.")


def _admin_error_response(request: Request, status_code: int, message: str) -> JSONResponse:
    payload: dict[str, Any] = {"error": message}
    request_id = _request_id_from_request(request)
    if request_id:
        payload["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=payload)


@lru_cache(maxsize=1)
def _admin_service() -> SupabaseAdminService:
    service = SupabaseAdminService(get_settings())
    if service.enabled:
        logger.info("ADMIN SERVICE READY | backend=supabase_http")
    else:
        logger.warning(
            "ADMIN SERVICE DISABLED | reason=%s",
            service.disabled_reason or "unknown",
        )
    return service


def _require_admin_service(request: Request) -> SupabaseAdminService:
    _require_admin_access(request)
    service = _admin_service()
    if not service.enabled:
        raise HTTPException(status_code=503, detail=service.disabled_reason or "Admin data service is unavailable.")
    return service


@lru_cache(maxsize=1)
def _chat_service() -> ChatService:
    settings = get_settings()
    return ChatService(
        api_key=settings.nvidia_api_key or settings.ai_api_key,
        model=settings.nvidia_chat_model,
        base_url=settings.ai_base_url,
    )


@lru_cache(maxsize=1)
def _gemini_service() -> GeminiChatService:
    settings = get_settings()
    return GeminiChatService(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        fallback_models=settings.gemini_fallback_models,
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
def _pollinations_service() -> PollinationsMediaService:
    settings = get_settings()
    return PollinationsMediaService(
        api_key=settings.pollinations_api_key,
        base_url=settings.pollinations_base_url,
        image_model_chat_gbt=settings.pollinations_image_model_chat_gbt,
        image_model_grok_imagine=settings.pollinations_image_model_grok_imagine,
        video_model_grok_text_to_video=settings.pollinations_video_model_grok_text_to_video,
        audio_model_gpt_audio=settings.pollinations_audio_model_gpt_audio,
        audio_voice_gpt_audio=settings.pollinations_audio_voice_gpt_audio,
    )


def _image_model_label(option: str) -> str:
    return IMAGE_MODEL_OPTION_LABELS.get(option, IMAGE_MODEL_LABEL_JO)


def _video_model_label(option: str) -> str:
    return VIDEO_MODEL_OPTION_LABELS.get(option, VIDEO_MODEL_LABEL_GROK_TEXT_TO_VIDEO)


def _image_model_id_for_option(settings, option: str) -> str:
    if option == IMAGE_MODEL_OPTION_CHAT_GBT:
        return settings.pollinations_image_model_chat_gbt
    if option == IMAGE_MODEL_OPTION_GROK_IMAGINE:
        return settings.pollinations_image_model_grok_imagine
    return settings.image_model


def _video_model_id_for_option(settings, option: str) -> str:
    _ = option
    return settings.pollinations_video_model_grok_text_to_video


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


def _image_extension_for_mime(mime_type: str | None) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized == "image/jpeg" or normalized == "image/jpg":
        return "jpg"
    if normalized == "image/webp":
        return "webp"
    if normalized == "image/gif":
        return "gif"
    return "png"


def _persist_image_bytes_to_local_asset(
    image_bytes: bytes,
    *,
    prefix: str,
    mime_type: str | None = None,
) -> tuple[str, str]:
    if not image_bytes:
        raise BackendError("Image payload is empty.", status_code=400)
    MEDIA_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(image_bytes).hexdigest()[:16]
    extension = _image_extension_for_mime(mime_type)
    filename = f"{prefix}_{int(time.time())}_{digest}.{extension}"
    asset_path = MEDIA_ASSETS_DIR / filename
    asset_path.write_bytes(image_bytes)
    return f"/media/{filename}", f"local_file:{filename}"


def _video_extension_for_mime(mime_type: str | None) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized in {"video/mp4", "video/mpeg4"}:
        return "mp4"
    if normalized == "video/webm":
        return "webm"
    if normalized == "video/quicktime":
        return "mov"
    return "mp4"


def _persist_video_bytes_to_local_asset(
    video_bytes: bytes,
    *,
    prefix: str,
    mime_type: str | None = None,
) -> tuple[str, str]:
    if not video_bytes:
        raise BackendError("Video payload is empty.", status_code=400)
    MEDIA_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(video_bytes).hexdigest()[:16]
    extension = _video_extension_for_mime(mime_type)
    filename = f"{prefix}_{int(time.time())}_{digest}.{extension}"
    asset_path = MEDIA_ASSETS_DIR / filename
    asset_path.write_bytes(video_bytes)
    return f"/media/{filename}", f"local_file:{filename}"


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


def _extract_gemini_mode_and_message(payload: GeminiRequest) -> tuple[GeminiMode, str]:
    raw_message = str(payload.message or "").strip()
    explicit_mode = payload.effective_mode
    command_match = re.match(r"^/(chat|image|img|voice|audio)\b\s*(.*)$", raw_message, flags=re.IGNORECASE)
    if command_match:
        command = command_match.group(1).strip().lower()
        mapped_mode: GeminiMode = (
            "image"
            if command in {"image", "img"}
            else "voice"
            if command in {"voice", "audio"}
            else "chat"
        )
        command_message = command_match.group(2).strip()
        effective_message = command_message or raw_message
        return mapped_mode, effective_message

    if explicit_mode == "image" and not raw_message:
        return "image", "Generate an image."
    if explicit_mode == "voice" and not raw_message:
        return "voice", "Generate speech."
    if explicit_mode == "video" and not raw_message:
        return "chat", "Video generation has moved to the dedicated Video Generation mode."
    if explicit_mode == "video":
        return "chat", raw_message
    return explicit_mode, raw_message


def _gemini_video_unavailable_message() -> str:
    return (
        "Video generation is now in the dedicated Video Generation feature. "
        "Use `/image your prompt` for image generation or `/voice your text` for audio in Gemini."
    )


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


async def _run_gemini_completion(message: str, model_override: str | None = None) -> str:
    service = _gemini_service()
    if not str(service.api_key or "").strip():
        raise _safe_service_error(status_code=503)
    try:
        return await service.generate_reply(message, model_override=model_override)
    except AIServiceError as exc:
        logger.warning("Gemini completion failed.", exc_info=True)
        safe_message = str(exc).strip() or SAFE_SERVICE_UNAVAILABLE_MESSAGE
        raise BackendError(safe_message, status_code=_status_code_for_ai_error(safe_message)) from exc


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
    max_attempts = 2
    last_error: AIServiceError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            generated = await _image_service().generate_image(prompt, size=size, ratio=ratio)
            if generated.image_bytes:
                return {"image_base64": base64.b64encode(generated.image_bytes).decode("utf-8")}
            if generated.image_url:
                return {"image_url": generated.image_url}
            raise AIServiceError("Image payload is missing.")
        except AIServiceError as exc:
            last_error = exc
            logger.warning(
                "Image generation failed | attempt=%s/%s error=%s",
                attempt,
                max_attempts,
                str(exc)[:220] or SAFE_SERVICE_UNAVAILABLE_MESSAGE,
                exc_info=True,
            )
            if attempt < max_attempts:
                await asyncio.sleep(0.7 * attempt)
                continue

    safe_message = str(last_error or "").strip() or SAFE_SERVICE_UNAVAILABLE_MESSAGE
    lowered = safe_message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        raise BackendError("Image generation timed out. Please retry.", status_code=504) from last_error
    raise BackendError(
        SAFE_SERVICE_UNAVAILABLE_MESSAGE,
        status_code=_status_code_for_ai_error(safe_message),
    ) from last_error


async def _generate_pollinations_image(*, prompt: str, size: str, model: str) -> dict[str, str]:
    max_attempts = 2
    last_error: AIServiceError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            generated = await _pollinations_service().generate_image(
                prompt=prompt,
                model=model,
                size=size,
                enhance=False,
            )
            if generated.image_bytes:
                return {"image_base64": base64.b64encode(generated.image_bytes).decode("utf-8")}
            if generated.image_url:
                return {"image_url": generated.image_url}
            raise AIServiceError("Image payload is missing.")
        except AIServiceError as exc:
            last_error = exc
            logger.warning(
                "Pollinations image generation failed | attempt=%s/%s error=%s",
                attempt,
                max_attempts,
                str(exc)[:220] or SAFE_SERVICE_UNAVAILABLE_MESSAGE,
            )
            if attempt < max_attempts:
                await asyncio.sleep(0.7 * attempt)
                continue

    safe_message = str(last_error or "").strip() or SAFE_SERVICE_UNAVAILABLE_MESSAGE
    lowered = safe_message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        raise BackendError("Image generation timed out. Please retry.", status_code=504) from last_error
    raise BackendError(SAFE_SERVICE_UNAVAILABLE_MESSAGE, status_code=_status_code_for_ai_error(safe_message)) from last_error


async def _generate_pollinations_video(
    *,
    prompt: str,
    model: str,
    duration_seconds: int,
    aspect_ratio: Literal["16:9", "9:16"],
) -> dict[str, str]:
    max_attempts = 2
    last_error: AIServiceError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            generated = await _pollinations_service().generate_video(
                prompt=prompt,
                model=model,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                enhance=False,
            )
            if generated.video_bytes:
                persisted_url, _storage_path = _persist_video_bytes_to_local_asset(
                    generated.video_bytes,
                    prefix="generated_video",
                    mime_type=generated.mime_type,
                )
                return {
                    "video_url": persisted_url,
                    "video_mime_type": generated.mime_type or "video/mp4",
                }
            if generated.video_url:
                return {
                    "video_url": generated.video_url,
                    "video_mime_type": generated.mime_type or "video/mp4",
                }
            raise AIServiceError("Video payload is missing.")
        except AIServiceError as exc:
            last_error = exc
            logger.warning(
                "Pollinations video generation failed | attempt=%s/%s error=%s",
                attempt,
                max_attempts,
                str(exc)[:220] or SAFE_SERVICE_UNAVAILABLE_MESSAGE,
            )
            if attempt < max_attempts:
                await asyncio.sleep(1.0 * attempt)
                continue

    safe_message = str(last_error or "").strip() or SAFE_SERVICE_UNAVAILABLE_MESSAGE
    lowered = safe_message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        raise BackendError("Video generation timed out. Please retry.", status_code=504) from last_error
    raise BackendError(SAFE_SERVICE_UNAVAILABLE_MESSAGE, status_code=_status_code_for_ai_error(safe_message)) from last_error


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


async def _generate_pollinations_audio(*, prompt: str) -> dict[str, str]:
    max_attempts = 2
    last_error: AIServiceError | None = None
    service = _pollinations_service()
    for attempt in range(1, max_attempts + 1):
        try:
            generated = await service.generate_audio(
                prompt=prompt,
                model=service.audio_model_gpt_audio,
                voice=service.audio_voice_gpt_audio,
                enhance=True,
            )
            return {
                "audio_base64": base64.b64encode(generated.audio_bytes).decode("utf-8"),
                "audio_mime_type": generated.mime_type,
                "audio_file_name": f"jo_ai_gpt_audio.{generated.file_extension}",
            }
        except AIServiceError as exc:
            last_error = exc
            logger.warning(
                "Pollinations audio generation failed | attempt=%s/%s error=%s",
                attempt,
                max_attempts,
                str(exc)[:220] or SAFE_SERVICE_UNAVAILABLE_MESSAGE,
            )
            if attempt < max_attempts:
                await asyncio.sleep(0.8 * attempt)
                continue

    safe_message = str(last_error or "").strip() or SAFE_SERVICE_UNAVAILABLE_MESSAGE
    lowered = safe_message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        raise BackendError("Audio generation timed out. Please retry.", status_code=504) from last_error
    raise BackendError(SAFE_SERVICE_UNAVAILABLE_MESSAGE, status_code=_status_code_for_ai_error(safe_message)) from last_error


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


async def _resolve_bot_username() -> str | None:
    cached = str(getattr(app.state, "bot_username", "") or "").strip()
    if cached:
        return cached
    runtime = _get_bot_runtime()
    if runtime is None:
        return None
    try:
        me = await runtime.bot.get_me()
    except Exception:
        logger.warning("Failed to resolve bot username for referral links.", exc_info=True)
        return None
    username = str(me.username or "").strip()
    if username:
        app.state.bot_username = username
        return username
    return None


def _video_join_required_text() -> str:
    return (
        "Please join the JO AI channel first to use Video Generation.\n"
        f"Join here: {VIDEO_JOIN_CHANNEL_URL}\n"
        "After joining, try again."
    )


async def _is_video_generation_allowed(telegram_id: int) -> bool:
    runtime = _get_bot_runtime()
    if runtime is None:
        logger.warning("Video membership check skipped: bot runtime unavailable.")
        return False
    try:
        member = await runtime.bot.get_chat_member(chat_id=VIDEO_JOIN_CHANNEL_USERNAME, user_id=telegram_id)
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, asyncio.TimeoutError):
        logger.warning("Video membership check failed for user=%s", telegram_id, exc_info=True)
        return False
    except Exception:
        logger.warning("Unexpected video membership check failure for user=%s", telegram_id, exc_info=True)
        return False
    status = str(getattr(member, "status", "")).strip().lower()
    return status in VIDEO_ALLOWED_MEMBERSHIP_STATUSES


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


def _resolve_frontend_source(request: Request) -> str:
    header_source = str(request.headers.get("x-frontend-source") or "").strip().lower()
    query_source = str(request.query_params.get("frontend_source") or "").strip().lower()
    candidate = header_source or query_source
    if candidate in {"telegram_bot", "mini_app", "website", "api"}:
        return candidate
    if candidate in {"bot", "telegram"}:
        return "telegram_bot"
    if candidate in {"miniapp", "webapp"}:
        return "mini_app"
    if candidate in {"web", "site"}:
        return "website"
    if candidate:
        return candidate[:40]

    init_data = str(request.headers.get("x-telegram-init-data") or "").strip()
    if init_data:
        return "mini_app"
    auth_header = str(request.headers.get("authorization") or "").strip().lower()
    if auth_header.startswith("tma "):
        return "mini_app"
    if request.url.path.startswith("/telegram/"):
        return "telegram_bot"
    return "api"


def _extract_referral_code(request: Request) -> str | None:
    def _sanitize_referral_code(raw_value: str | None) -> str | None:
        raw = str(raw_value or "").strip().lower()
        if not raw:
            return None
        normalized = raw[4:] if raw.startswith("ref_") or raw.startswith("ref-") else raw
        cleaned = "".join(ch for ch in normalized if ch.isalnum() or ch in {"_", "-"})
        return cleaned[:64] or None

    for key in ("ref", "referral", "referral_code", "start", "startapp"):
        value = _sanitize_referral_code(request.query_params.get(key))
        if value:
            return value
    header_value = _sanitize_referral_code(request.headers.get("x-referral-code"))
    if header_value:
        return header_value
    return None


def _extract_conversation_id(request: Request, identity: TrackingIdentity | None, feature_used: str) -> str:
    explicit = str(request.headers.get("x-conversation-id") or "").strip()
    if not explicit:
        explicit = str(request.query_params.get("conversation_id") or "").strip()
    if explicit:
        return explicit[:120]
    if identity is None:
        return f"anon:{feature_used}:{datetime.now(timezone.utc).date().isoformat()}"
    return f"{identity.telegram_id}:{feature_used}:{datetime.now(timezone.utc).date().isoformat()}"


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
    frontend_source: str | None = None,
    feature_used: str | None = None,
    conversation_id: str | None = None,
    text_content: str | None = None,
    media: TrackingMedia | None = None,
    mark_started: bool = False,
    referral_code: str | None = None,
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
                frontend_source=frontend_source,
                feature_used=feature_used,
                conversation_id=conversation_id,
                text_content=text_content,
                media=media,
                mark_started=mark_started,
                started_via_referral=referral_code,
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
app.state.keepalive_task = None
app.state.heartbeat_task = None
app.state.engagement_task = None
app.state.bot_username = ""
app.state.started_at = time.time()

if ADMIN_FRONTEND_DIR.exists():
    app.mount("/admin/static", StaticFiles(directory=str(ADMIN_FRONTEND_DIR)), name="admin-static")
else:
    logger.warning("ADMIN FRONTEND MISSING | expected_dir=%s", ADMIN_FRONTEND_DIR)

MEDIA_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_ASSETS_DIR)), name="media-assets")

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


def _is_blocked_delivery_error(exc: Exception) -> bool:
    if isinstance(exc, TelegramForbiddenError):
        return True
    lowered = str(exc).lower()
    blocked_markers = (
        "bot was blocked",
        "user is deactivated",
        "forbidden",
        "chat not found",
        "have no rights to send a message",
    )
    return any(marker in lowered for marker in blocked_markers)


async def _send_bot_message_with_tracking(
    *,
    runtime: BotRuntime,
    tracking_service: SupabaseTrackingService,
    telegram_id: int,
    text: str,
    purpose: str,
) -> bool:
    try:
        await runtime.bot.send_message(chat_id=telegram_id, text=text)
        await tracking_service.mark_delivery_success(telegram_id)
        return True
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        blocked = _is_blocked_delivery_error(exc)
        await tracking_service.mark_delivery_failure(telegram_id, str(exc), blocked=blocked)
        logger.warning(
            "%s delivery failed | telegram_id=%s blocked=%s error=%s",
            purpose,
            telegram_id,
            blocked,
            exc,
        )
    except TelegramNetworkError as exc:
        logger.warning("%s delivery network error | telegram_id=%s error=%s", purpose, telegram_id, exc)
    except Exception as exc:
        logger.warning("%s delivery failed | telegram_id=%s error=%s", purpose, telegram_id, exc, exc_info=True)
    return False


async def _keepalive_self_ping_loop() -> None:
    settings = get_settings()
    if not settings.keepalive_self_ping_enabled:
        logger.info("Keepalive self-ping loop disabled.")
        return

    interval_seconds = max(
        KEEPALIVE_MIN_LOOP_SECONDS,
        int(settings.keepalive_ping_interval_minutes) * 60,
    )
    base_url = (
        str(settings.public_base_url or "").strip()
        or str(_read_env("RENDER_EXTERNAL_URL") or "").strip()
        or f"http://127.0.0.1:{_read_env('PORT') or '8000'}"
    ).rstrip("/")
    target_url = f"{base_url}/api/health"

    timeout = aiohttp.ClientTimeout(total=15)
    logger.info("Keepalive self-ping loop started | target=%s interval_seconds=%s", target_url, interval_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                started = time.perf_counter()
                async with session.get(target_url) as response:
                    _ = await response.text()
                    duration_ms = round((time.perf_counter() - started) * 1000, 2)
                    if response.status < 400:
                        logger.info(
                            "KEEPALIVE SELF-PING SUCCESS | status=%s duration_ms=%s",
                            response.status,
                            duration_ms,
                        )
                    else:
                        logger.warning(
                            "KEEPALIVE SELF-PING FAILED | status=%s duration_ms=%s",
                            response.status,
                            duration_ms,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("KEEPALIVE SELF-PING ERROR | target=%s error=%s", target_url, exc)
            await asyncio.sleep(interval_seconds)


async def _heartbeat_loop(runtime: BotRuntime, tracking_service: SupabaseTrackingService) -> None:
    settings = get_settings()
    if not settings.keepalive_heartbeat_enabled:
        logger.info("Heartbeat loop disabled.")
        return
    heartbeat_id = int(settings.keepalive_heartbeat_telegram_id or 0)
    if heartbeat_id <= 0:
        logger.warning("Heartbeat loop disabled due to missing KEEPALIVE_HEARTBEAT_TELEGRAM_ID.")
        return

    heartbeat_text = str(settings.keepalive_heartbeat_message or "").strip() or "I'm making your bot active automatically."
    interval_seconds = max(
        KEEPALIVE_MIN_LOOP_SECONDS,
        int(settings.keepalive_heartbeat_interval_minutes) * 60,
    )
    logger.info("Heartbeat loop started | target=%s interval_seconds=%s", heartbeat_id, interval_seconds)
    while True:
        try:
            await _send_bot_message_with_tracking(
                runtime=runtime,
                tracking_service=tracking_service,
                telegram_id=heartbeat_id,
                text=heartbeat_text,
                purpose="HEARTBEAT",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Heartbeat loop error | target=%s error=%s", heartbeat_id, exc, exc_info=True)
        await asyncio.sleep(interval_seconds)


async def _engagement_loop(runtime: BotRuntime, tracking_service: SupabaseTrackingService) -> None:
    poll_interval_seconds = 180
    logger.info("Engagement loop started | poll_interval_seconds=%s", poll_interval_seconds)
    while True:
        try:
            settings = get_settings()
            config = {
                "enabled": bool(settings.engagement_enabled),
                "message_template": settings.engagement_message_template,
                "inactivity_minutes": int(settings.engagement_inactivity_minutes),
                "cooldown_minutes": int(settings.engagement_cooldown_minutes),
                "batch_size": int(settings.engagement_batch_size),
            }
            try:
                admin_config = await asyncio.to_thread(_admin_service().get_engagement_config)
                loaded = admin_config.get("config") if isinstance(admin_config, dict) else None
                if isinstance(loaded, dict):
                    config["enabled"] = bool(loaded.get("enabled", config["enabled"]))
                    config["message_template"] = str(loaded.get("message_template") or config["message_template"])
                    config["inactivity_minutes"] = int(loaded.get("inactivity_minutes") or config["inactivity_minutes"])
                    config["cooldown_minutes"] = int(loaded.get("cooldown_minutes") or config["cooldown_minutes"])
                    config["batch_size"] = int(loaded.get("batch_size") or config["batch_size"])
            except Exception:
                logger.warning("Engagement config fetch failed; using env defaults.", exc_info=True)

            if not bool(config["enabled"]):
                await asyncio.sleep(poll_interval_seconds)
                continue

            text = str(config["message_template"] or "").strip() or settings.engagement_message_template
            inactivity_minutes = max(30, int(config["inactivity_minutes"]))
            cooldown_minutes = max(30, int(config["cooldown_minutes"]))
            batch_size = max(1, min(500, int(config["batch_size"])))

            candidates = await tracking_service.fetch_engagement_candidates(
                inactivity_minutes=inactivity_minutes,
                cooldown_minutes=cooldown_minutes,
                limit=batch_size,
            )
            for candidate in candidates:
                telegram_id = int(candidate.get("telegram_id") or 0)
                if telegram_id <= 0:
                    continue
                delivered = await _send_bot_message_with_tracking(
                    runtime=runtime,
                    tracking_service=tracking_service,
                    telegram_id=telegram_id,
                    text=text,
                    purpose="ENGAGEMENT",
                )
                if delivered:
                    await tracking_service.mark_engagement_sent(telegram_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Engagement loop error: %s", exc, exc_info=True)
        await asyncio.sleep(poll_interval_seconds)


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
    admin_service = _admin_service()
    logger.info(
        "ADMIN DASHBOARD CONFIG | telegram_auth_enabled=%s token_auth_enabled=%s allowlist_count=%s owner_telegram_id_set=%s frontend_present=%s service_enabled=%s",
        bool(_admin_allowlist()),
        bool(_configured_admin_signin_token()),
        len(_admin_allowlist()),
        bool(_admin_owner_telegram_id()),
        ADMIN_FRONTEND_DIR.exists(),
        admin_service.enabled,
    )
    if not admin_service.enabled:
        logger.warning("ADMIN DASHBOARD SERVICE DISABLED | reason=%s", admin_service.disabled_reason or "unknown")
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
    app.state.keepalive_task = asyncio.create_task(_keepalive_self_ping_loop(), name="keepalive-self-ping")
    app.state.heartbeat_task = asyncio.create_task(
        _heartbeat_loop(runtime, tracking_service),
        name="keepalive-heartbeat",
    )
    app.state.engagement_task = asyncio.create_task(
        _engagement_loop(runtime, tracking_service),
        name="engagement-loop",
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    telegram_startup_task = getattr(app.state, "telegram_startup_task", None)
    if isinstance(telegram_startup_task, asyncio.Task):
        telegram_startup_task.cancel()
        with suppress(asyncio.CancelledError):
            await telegram_startup_task
    app.state.telegram_startup_task = None

    for task_name in ("engagement_task", "heartbeat_task", "keepalive_task"):
        task = getattr(app.state, task_name, None)
        if isinstance(task, asyncio.Task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        setattr(app.state, task_name, None)

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


@app.get("/api/referral/me")
async def referral_me(request: Request) -> JSONResponse:
    identity = _resolve_tracking_identity(request)
    if identity is None:
        return JSONResponse(status_code=401, content={"error": "Telegram identity is required."})

    frontend_source = _resolve_frontend_source(request)
    service = _tracking_service()
    referral_code = await service.ensure_referral_code(identity=identity, frontend_source=frontend_source)
    bot_username = await _resolve_bot_username()
    settings = get_settings()

    telegram_link = f"https://t.me/{bot_username}?start={referral_code}" if bot_username else ""
    miniapp_base = str(settings.miniapp_url or DEFAULT_GITHUB_PAGES_URL).strip() or DEFAULT_GITHUB_PAGES_URL
    separator = "&" if "?" in miniapp_base else "?"
    miniapp_link = f"{miniapp_base}{separator}ref={referral_code}"

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "referral_code": referral_code,
            "telegram_link": telegram_link,
            "miniapp_link": miniapp_link,
            "frontend_source": frontend_source,
        },
    )


@app.post("/api/referral/claim")
async def referral_claim(request: Request, payload: ReferralClaimRequest) -> JSONResponse:
    identity = _resolve_tracking_identity(request, payload)
    if identity is None:
        return JSONResponse(status_code=401, content={"error": "Telegram identity is required."})

    frontend_source = (
        str(payload.frontend_source or "").strip().lower() or _resolve_frontend_source(request)
    )
    referral_code = str(payload.referral_code or "").strip().lower()
    if referral_code.startswith("ref_") or referral_code.startswith("ref-"):
        referral_code = referral_code[4:]
    referral_code = "".join(ch for ch in referral_code if ch.isalnum() or ch in {"_", "-"})[:64]
    if not referral_code:
        return JSONResponse(status_code=400, content={"error": "Referral code is required."})

    await _track_api_action(
        identity=identity,
        message_type="referral_claim",
        user_message=f"claim:{referral_code}",
        bot_reply="Referral claimed",
        model_used=None,
        success=True,
        message_increment=0,
        image_increment=0,
        frontend_source=frontend_source,
        feature_used="referral",
        conversation_id=_extract_conversation_id(request, identity, "referral"),
        text_content="Referral claimed",
        mark_started=True,
        referral_code=referral_code,
    )
    return JSONResponse(status_code=200, content={"ok": True, "referral_code": referral_code})


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
def admin_dashboard_page() -> HTMLResponse:
    index_path = ADMIN_FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            content="Admin dashboard assets are missing. Deploy the /admin frontend files.",
            status_code=503,
        )
    return FileResponse(index_path)


@app.get("/api/admin/status")
def admin_status() -> dict[str, Any]:
    service = _admin_service()
    allowlist = _admin_allowlist()
    owner_id = _admin_owner_telegram_id()
    token_auth_enabled = bool(_configured_admin_signin_token())
    return {
        "ok": True,
        "auth_required": True,
        "telegram_auth_enabled": bool(allowlist),
        "token_auth_enabled": token_auth_enabled,
        "telegram_id_shortcut_enabled": bool(owner_id),
        "allowlist_count": len(allowlist),
        "owner_telegram_id_configured": bool(owner_id),
        "owner_telegram_id": owner_id,
        "service_enabled": service.enabled,
        "service_reason": service.disabled_reason if not service.enabled else "",
    }


@app.get("/api/admin/auth")
def admin_auth_check(request: Request) -> JSONResponse:
    try:
        _require_admin_access(request)
        service = _admin_service()
        if not service.enabled:
            raise HTTPException(status_code=503, detail=service.disabled_reason or "Admin data service is unavailable.")
        session_payload = _admin_session_payload(_extract_admin_token(request))
        telegram_id = _parse_positive_int(session_payload.get("telegram_id") if session_payload else None)
        logger.info("ADMIN AUTH SUCCESS | request_id=%s", _request_id_from_request(request) or "unknown")
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "version": VERSION,
                "telegram_id": telegram_id,
                "auth_method": str(session_payload.get("auth_method") or "unknown") if isinstance(session_payload, dict) else "unknown",
            },
        )
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))


def _complete_admin_telegram_auth(request: Request, telegram_id: int | None, auth_method: str) -> JSONResponse:
    owner_id = _admin_owner_telegram_id()
    if owner_id is None:
        return _admin_error_response(request, 503, "Admin owner Telegram ID is not configured.")
    if telegram_id is None:
        return _admin_error_response(request, 401, "Telegram identity is missing or invalid.")
    if int(telegram_id) != int(owner_id):
        logger.warning(
            "ADMIN TELEGRAM AUTH FAILED | request_id=%s telegram_id=%s owner_id=%s reason=owner_mismatch",
            _request_id_from_request(request) or "unknown",
            telegram_id,
            owner_id,
        )
        return _admin_error_response(request, 403, "This Telegram account is not allowed for admin access.")

    service = _admin_service()
    if not service.enabled:
        return _admin_error_response(request, 503, service.disabled_reason or "Admin data service is unavailable.")
    if not service.is_known_telegram_user(int(telegram_id)):
        logger.warning(
            "ADMIN TELEGRAM AUTH FAILED | request_id=%s telegram_id=%s reason=not_in_user_db",
            _request_id_from_request(request) or "unknown",
            telegram_id,
        )
        return _admin_error_response(request, 403, "Telegram ID is not present in the bot database.")

    session_payload = _issue_admin_session_token(int(telegram_id), auth_method=auth_method)
    logger.info(
        "ADMIN TELEGRAM AUTH SUCCESS | request_id=%s telegram_id=%s auth_method=%s",
        _request_id_from_request(request) or "unknown",
        telegram_id,
        auth_method,
    )
    response = JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "auth_method": auth_method,
            "token": session_payload["token"],
            "expires_at": session_payload["expires_at"],
            "ttl_seconds": session_payload["ttl_seconds"],
            "telegram_id": session_payload["telegram_id"],
        },
    )
    _set_admin_session_cookie(response, str(session_payload["token"]), request=request)
    return response


def _complete_admin_token_auth(request: Request, raw_token: str) -> JSONResponse:
    configured = _configured_admin_signin_token()
    if not configured:
        return _admin_error_response(request, 503, "Admin token sign-in is not configured.")
    if not _validate_admin_signin_token(raw_token):
        logger.warning(
            "ADMIN TOKEN AUTH FAILED | request_id=%s reason=invalid_token",
            _request_id_from_request(request) or "unknown",
        )
        return _admin_error_response(request, 401, "Invalid admin token.")

    service = _admin_service()
    if not service.enabled:
        return _admin_error_response(request, 503, service.disabled_reason or "Admin data service is unavailable.")

    owner_id = _admin_owner_telegram_id()
    if owner_id and not service.is_known_telegram_user(int(owner_id)):
        logger.warning(
            "ADMIN TOKEN AUTH FAILED | request_id=%s owner_id=%s reason=owner_not_in_user_db",
            _request_id_from_request(request) or "unknown",
            owner_id,
        )
        return _admin_error_response(request, 403, "Admin owner Telegram ID is not present in the bot database.")

    session_payload = _issue_admin_session_token(int(owner_id or 0), auth_method="token")
    logger.info(
        "ADMIN TOKEN AUTH SUCCESS | request_id=%s owner_id=%s",
        _request_id_from_request(request) or "unknown",
        owner_id or "unknown",
    )
    response = JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "auth_method": "token",
            "token": session_payload["token"],
            "expires_at": session_payload["expires_at"],
            "ttl_seconds": session_payload["ttl_seconds"],
            "telegram_id": owner_id,
        },
    )
    _set_admin_session_cookie(response, str(session_payload["token"]), request=request)
    return response


@app.get("/api/admin/auth/telegram")
def admin_telegram_auth(request: Request) -> JSONResponse:
    telegram_id = _resolve_admin_telegram_id(request)
    if telegram_id is None:
        return _admin_error_response(
            request,
            401,
            "Telegram identity is missing or invalid. Use Telegram login from this dashboard.",
        )
    return _complete_admin_telegram_auth(request, telegram_id, auth_method="telegram_webapp")


@app.post("/api/admin/auth/telegram")
async def admin_telegram_auth_widget(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _admin_error_response(request, 400, "Invalid Telegram login payload.")
    if not isinstance(payload, dict):
        return _admin_error_response(request, 400, "Invalid Telegram login payload.")
    telegram_id = _resolve_admin_telegram_id_from_widget_payload(request, payload)
    if telegram_id is None:
        return _admin_error_response(request, 401, "Telegram identity is missing or invalid.")
    return _complete_admin_telegram_auth(request, telegram_id, auth_method="telegram_widget")


@app.post("/api/admin/auth/token")
def admin_token_auth(request: Request, payload: AdminTokenAuthRequest) -> JSONResponse:
    return _complete_admin_token_auth(request, payload.token)


@app.post("/api/admin/auth/logout")
def admin_logout(request: Request) -> JSONResponse:
    token = _extract_admin_token(request)
    if token:
        _ADMIN_SESSION_TOKENS.pop(token, None)
    response = JSONResponse(status_code=200, content={"ok": True})
    _clear_admin_session_cookie(response)
    return response


@app.get("/api/admin/overview")
async def admin_overview(request: Request, days: int = 14) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        safe_days = max(7, min(90, int(days)))
        payload = await asyncio.to_thread(service.get_overview, safe_days)
        logger.info(
            "ADMIN OVERVIEW SUCCESS | request_id=%s days=%s",
            _request_id_from_request(request) or "unknown",
            safe_days,
        )
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN OVERVIEW FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load dashboard overview.")


@app.get("/api/admin/messages")
async def admin_messages(
    request: Request,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    message_type: str | None = None,
    scope: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    frontend_source: str | None = None,
    feature_used: str | None = None,
) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        payload = await asyncio.to_thread(
            service.get_messages,
            limit=max(1, min(100, int(limit))),
            offset=max(0, int(offset)),
            search=search,
            message_type=message_type,
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            frontend_source=frontend_source,
            feature_used=feature_used,
        )
        logger.info(
            "ADMIN MESSAGES SUCCESS | request_id=%s limit=%s offset=%s",
            _request_id_from_request(request) or "unknown",
            payload.get("limit"),
            payload.get("offset"),
        )
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN MESSAGES FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load messages.")


@app.get("/api/admin/users")
async def admin_users(
    request: Request,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    active_days: int = 7,
) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        payload = await asyncio.to_thread(
            service.get_users,
            limit=max(1, min(100, int(limit))),
            offset=max(0, int(offset)),
            search=search,
            active_days=max(1, min(60, int(active_days))),
        )
        logger.info(
            "ADMIN USERS SUCCESS | request_id=%s limit=%s offset=%s",
            _request_id_from_request(request) or "unknown",
            payload.get("limit"),
            payload.get("offset"),
        )
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN USERS FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load users.")


@app.get("/api/admin/media")
@app.get("/api/admin/images")
async def admin_media(
    request: Request,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        payload = await asyncio.to_thread(
            service.get_media,
            limit=max(1, min(100, int(limit))),
            offset=max(0, int(offset)),
            search=search,
        )
        logger.info(
            "ADMIN MEDIA SUCCESS | request_id=%s limit=%s offset=%s",
            _request_id_from_request(request) or "unknown",
            payload.get("limit"),
            payload.get("offset"),
        )
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN MEDIA FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load media history.")


@app.get("/api/admin/analytics")
async def admin_analytics(request: Request, days: int = 30, top_limit: int = 10) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        payload = await asyncio.to_thread(
            service.get_analytics,
            days=max(7, min(180, int(days))),
            top_limit=max(3, min(30, int(top_limit))),
        )
        logger.info(
            "ADMIN ANALYTICS SUCCESS | request_id=%s days=%s",
            _request_id_from_request(request) or "unknown",
            payload.get("window_days"),
        )
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN ANALYTICS FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load analytics.")


@app.get("/api/admin/referrals")
async def admin_referrals(
    request: Request,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        payload = await asyncio.to_thread(
            service.get_referrals,
            limit=max(1, min(200, int(limit))),
            offset=max(0, int(offset)),
            search=search,
        )
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN REFERRALS FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load referrals.")


@app.get("/api/admin/engagement")
async def admin_engagement_get(request: Request) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        payload = await asyncio.to_thread(service.get_engagement_config)
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN ENGAGEMENT GET FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load engagement settings.")


@app.post("/api/admin/engagement")
async def admin_engagement_update(request: Request, payload: EngagementConfigUpdateRequest) -> JSONResponse:
    try:
        service = _require_admin_service(request)
        updated = await asyncio.to_thread(service.update_engagement_config, payload.model_dump(exclude_none=True))
        return JSONResponse(status_code=200, content=updated)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN ENGAGEMENT UPDATE FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to update engagement settings.")


@app.get("/api/admin/bot-status")
def admin_bot_status(request: Request) -> JSONResponse:
    try:
        _require_admin_access(request)
        runtime = _get_bot_runtime()
        startup_task = getattr(app.state, "telegram_startup_task", None)
        keepalive_task = getattr(app.state, "keepalive_task", None)
        heartbeat_task = getattr(app.state, "heartbeat_task", None)
        engagement_task = getattr(app.state, "engagement_task", None)
        payload = {
            "ok": True,
            "runtime_ready": runtime is not None,
            "telegram_ready": bool(getattr(runtime, "telegram_ready", False)) if runtime else False,
            "webhook_configured": bool(getattr(runtime, "webhook_configured", False)) if runtime else False,
            "menu_button_configured": bool(getattr(runtime, "menu_button_configured", False)) if runtime else False,
            "last_startup_error": str(getattr(runtime, "last_startup_error", "") or ""),
            "startup_warnings": list(getattr(runtime, "startup_warnings", []) or []) if runtime else [],
            "startup_task_running": bool(isinstance(startup_task, asyncio.Task) and not startup_task.done()),
            "keepalive_task_running": bool(isinstance(keepalive_task, asyncio.Task) and not keepalive_task.done()),
            "heartbeat_task_running": bool(isinstance(heartbeat_task, asyncio.Task) and not heartbeat_task.done()),
            "engagement_task_running": bool(isinstance(engagement_task, asyncio.Task) and not engagement_task.done()),
            "uptime_seconds": round(_uptime_seconds(), 2),
        }
        return JSONResponse(status_code=200, content=payload)
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN BOT STATUS FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load bot status.")


@app.get("/api/admin/logs")
def admin_logs(request: Request, limit: int = 200, level: str | None = None, search: str | None = None) -> JSONResponse:
    try:
        _require_admin_access(request)
        safe_limit = max(20, min(1000, int(limit)))
        level_filter = str(level or "").strip().upper()
        search_filter = str(search or "").strip().lower()
        log_files = [
            PROJECT_ROOT / "logs" / "bot.log",
            PROJECT_ROOT / "logs" / "app.log",
        ]
        lines: list[str] = []
        for path in log_files:
            if not path.exists():
                continue
            try:
                file_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for line in file_lines[-3000:]:
                prefix = f"[{path.name}] "
                lines.append(f"{prefix}{line}")
        if level_filter:
            lines = [line for line in lines if f" {level_filter} " in line or line.startswith(f"[{level_filter}]")]
        if search_filter:
            lines = [line for line in lines if search_filter in line.lower()]
        lines = lines[-safe_limit:]
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "items": lines,
                "total": len(lines),
                "limit": safe_limit,
            },
        )
    except HTTPException as exc:
        return _admin_error_response(request, exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.exception("ADMIN LOGS FAILED | request_id=%s error=%s", _request_id_from_request(request), exc)
        return _admin_error_response(request, 500, "Failed to load logs.")


@app.get("/api/admin/media/proxy")
async def admin_media_proxy(request: Request, ref: str) -> Response:
    _require_admin_access(request)
    raw_ref = str(ref or "").strip()
    if not raw_ref:
        raise HTTPException(status_code=400, detail="Missing media reference.")

    if raw_ref.startswith("telegram_file:"):
        file_id = raw_ref.split(":", maxsplit=1)[1].strip()
        if not file_id:
            raise HTTPException(status_code=400, detail="Invalid Telegram media reference.")
        runtime = _get_bot_runtime()
        if runtime is None:
            raise HTTPException(status_code=503, detail="Bot runtime is not ready.")
        try:
            file_info = await runtime.bot.get_file(file_id)
            stream = await runtime.bot.download_file(file_info.file_path)
            payload = stream.read()
        except Exception as exc:
            logger.warning("ADMIN MEDIA PROXY FAILED | ref=%s error=%s", raw_ref, exc, exc_info=True)
            raise HTTPException(status_code=404, detail="Media file is unavailable.") from exc

        file_path = str(getattr(file_info, "file_path", "") or "").lower()
        media_type = "application/octet-stream"
        if file_path.endswith(".png"):
            media_type = "image/png"
        elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
            media_type = "image/jpeg"
        elif file_path.endswith(".webp"):
            media_type = "image/webp"
        elif file_path.endswith(".gif"):
            media_type = "image/gif"
        elif file_path.endswith(".mp4"):
            media_type = "video/mp4"
        elif file_path.endswith(".webm"):
            media_type = "video/webm"
        elif file_path.endswith(".mov"):
            media_type = "video/quicktime"
        return Response(content=payload, media_type=media_type)

    raise HTTPException(status_code=400, detail="Unsupported media reference.")


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
    frontend_source = _resolve_frontend_source(request)
    feature_used = str(mode).strip() or "chat"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    referral_code = _extract_referral_code(request)
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=message,
            mark_started=bool(identity),
            referral_code=referral_code,
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=str(payload.get("output", output)),
            mark_started=bool(identity),
            referral_code=referral_code,
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=message,
            mark_started=bool(identity),
            referral_code=referral_code,
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


@app.post("/gemini")
@app.post("/api/gemini")
async def gemini_endpoint(request: Request, payload: GeminiRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    frontend_source = _resolve_frontend_source(request)
    referral_code = _extract_referral_code(request)
    gemini_mode, user_message = _extract_gemini_mode_and_message(payload)
    feature_used = f"gemini_{gemini_mode}"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    tracking_model = str(payload.model or settings.gemini_model).strip() or settings.gemini_model

    if GEMINI_TEMP_DISABLED:
        disabled_message = (
            "Gemini is temporarily disabled while image generation is being stabilized. "
            "Use /image for image generation."
        )
        await _track_api_action(
            identity=identity,
            message_type="gemini",
            user_message=user_message,
            bot_reply=disabled_message,
            model_used=tracking_model,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_message,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        logger.info(
            "GEMINI TEMP DISABLED | request_id=%s user=%s mode=%s",
            request_id or "unknown",
            user_id,
            gemini_mode,
        )
        payload_response: dict[str, Any] = {"error": disabled_message, "mode": "gemini_disabled"}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=503, content=payload_response)

    refusal = _maybe_block_sensitive_request(user_message)
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="gemini",
            user_message=user_message,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=tracking_model,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_message,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        return refusal

    try:
        if gemini_mode == "image":
            result_payload = await _generate_image(
                prompt=user_message,
                size=payload.effective_size,
                ratio=payload.effective_ratio,
            )
            response_payload: dict[str, Any] = {
                "output": "Gemini image request completed.",
                "mode": "gemini_image",
                "ratio": payload.effective_ratio,
            }
            response_payload.update(result_payload)
            persisted_storage_path: str | None = None
            if not str(response_payload.get("image_url") or "").strip() and str(response_payload.get("image_base64") or "").strip():
                try:
                    generated_bytes = _decode_base64_image(str(response_payload.get("image_base64") or ""))
                    persisted_media_url, persisted_storage_path = _persist_image_bytes_to_local_asset(
                        generated_bytes,
                        prefix="gemini_generated",
                        mime_type="image/png",
                    )
                    response_payload["image_url"] = persisted_media_url
                except BackendError as exc:
                    logger.warning("Gemini image local persistence failed: %s", exc.message)
            await _track_api_action(
                identity=identity,
                message_type="gemini",
                user_message=user_message,
                bot_reply=str(response_payload.get("output", "Gemini image request completed.")),
                model_used=tracking_model,
                success=True,
                image_increment=1,
                frontend_source=frontend_source,
                feature_used=feature_used,
                conversation_id=conversation_id,
                text_content=str(response_payload.get("output", "Gemini image request completed.")),
                media=TrackingMedia(
                    media_type="image",
                    media_url=str(response_payload.get("image_url") or "").strip() or None,
                    storage_path=(
                        persisted_storage_path
                        or (None if str(response_payload.get("image_url") or "").strip() else "inline_base64:response")
                    ),
                    mime_type="image/png" if "image_base64" in response_payload else None,
                    provider_source="gemini",
                    media_origin="generated",
                    media_status="available" if ("image_url" in response_payload or "image_base64" in response_payload) else "missing",
                    media_error_reason=None if ("image_url" in response_payload or "image_base64" in response_payload) else "missing_image_payload",
                ),
                mark_started=bool(identity),
                referral_code=referral_code,
            )
            return JSONResponse(status_code=200, content=response_payload)

        if gemini_mode == "voice":
            generated = await _generate_tts(
                text=user_message,
                language=payload.effective_language,
                voice=payload.effective_voice,
                emotion=payload.effective_emotion,
            )
            response_payload: dict[str, Any] = {
                "output": "Gemini voice request completed.",
                "mode": "gemini_voice",
                "language": payload.effective_language,
                "voice": payload.effective_voice,
                "emotion": payload.effective_emotion,
            }
            response_payload.update(generated)
            await _track_api_action(
                identity=identity,
                message_type="gemini",
                user_message=user_message,
                bot_reply=str(response_payload.get("output", "Gemini voice request completed.")),
                model_used=tracking_model,
                success=True,
                message_increment=1,
                frontend_source=frontend_source,
                feature_used=feature_used,
                conversation_id=conversation_id,
                text_content=str(response_payload.get("output", "Gemini voice request completed.")),
                media=TrackingMedia(
                    media_type="audio",
                    mime_type=str(response_payload.get("audio_mime_type") or "audio/mpeg"),
                    provider_source="gemini",
                    media_origin="generated",
                    media_status="available",
                ),
                mark_started=bool(identity),
                referral_code=referral_code,
            )
            return JSONResponse(status_code=200, content=response_payload)

        if gemini_mode == "video":
            output = _gemini_video_unavailable_message()
            await _track_api_action(
                identity=identity,
                message_type="gemini",
                user_message=user_message,
                bot_reply=output,
                model_used=tracking_model,
                success=False,
                message_increment=1,
                frontend_source=frontend_source,
                feature_used=feature_used,
                conversation_id=conversation_id,
                text_content=output,
                mark_started=bool(identity),
                referral_code=referral_code,
            )
            return JSONResponse(status_code=200, content={"output": output, "mode": "gemini_video"})

        output = await _run_gemini_completion(user_message, model_override=payload.model)
        await _track_api_action(
            identity=identity,
            message_type="gemini",
            user_message=user_message,
            bot_reply=output,
            model_used=tracking_model,
            success=True,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=output,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        return JSONResponse(status_code=200, content={"output": output, "mode": "gemini_chat"})
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="gemini",
            user_message=user_message,
            bot_reply=exc.message,
            model_used=tracking_model,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_message,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        payload_response: dict[str, Any] = {"error": exc.message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload_response)


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
    frontend_source = _resolve_frontend_source(request)
    feature_used = "image_generation"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    referral_code = _extract_referral_code(request)
    user_prompt = payload.effective_prompt
    image_model_option = payload.effective_model_option
    image_model_label = _image_model_label(image_model_option)
    image_model_id = _image_model_id_for_option(settings, image_model_option)
    provider_source = "jo_ai" if image_model_option == IMAGE_MODEL_OPTION_JO else "pollinations"
    logger.info(
        "API IMAGE START | request_id=%s user=%s prompt_len=%s ratio=%s model=%s",
        request_id or "unknown",
        user_id,
        len(user_prompt or ""),
        payload.effective_ratio,
        image_model_label,
    )
    refusal = _maybe_block_sensitive_request(payload.effective_prompt, payload.ratio)
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=image_model_label,
            success=False,
            image_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{image_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        logger.info(
            "API IMAGE REFUSED | request_id=%s user=%s",
            request_id or "unknown",
            user_id,
        )
        return refusal
    try:
        enhanced_prompt = build_enhanced_image_prompt(user_prompt, ratio=payload.effective_ratio)
        prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "API IMAGE ENHANCED | request_id=%s user=%s prompt_hash=%s enhanced_len=%s",
            request_id or "unknown",
            user_id,
            prompt_hash,
            len(enhanced_prompt),
        )
        if image_model_option == IMAGE_MODEL_OPTION_JO:
            result_payload = await asyncio.wait_for(
                _generate_image(
                    prompt=enhanced_prompt,
                    size=payload.effective_size,
                    ratio=payload.effective_ratio,
                ),
                timeout=IMAGE_ENDPOINT_TIMEOUT_SECONDS,
            )
        else:
            result_payload = await asyncio.wait_for(
                _generate_pollinations_image(
                    prompt=enhanced_prompt,
                    size=payload.effective_size,
                    model=image_model_id,
                ),
                timeout=IMAGE_ENDPOINT_TIMEOUT_SECONDS,
            )
        response_payload: dict[str, Any] = {
            "output": user_prompt,
            "ratio": payload.effective_ratio,
            "model_label": image_model_label,
        }
        response_payload.update(result_payload)
        persisted_storage_path: str | None = None
        if not str(response_payload.get("image_url") or "").strip() and str(response_payload.get("image_base64") or "").strip():
            try:
                generated_bytes = _decode_base64_image(str(response_payload.get("image_base64") or ""))
                persisted_media_url, persisted_storage_path = _persist_image_bytes_to_local_asset(
                    generated_bytes,
                    prefix="generated",
                    mime_type="image/png",
                )
                response_payload["image_url"] = persisted_media_url
            except BackendError as exc:
                logger.warning("Generated image local persistence failed: %s", exc.message)
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=str(response_payload.get("output", "Image generated successfully.")),
            model_used=image_model_label,
            success=True,
            image_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{image_model_option}",
            conversation_id=conversation_id,
            text_content=str(response_payload.get("output", "Image generated successfully.")),
            media=TrackingMedia(
                media_type="image",
                media_url=str(response_payload.get("image_url") or "").strip() or None,
                storage_path=(
                    persisted_storage_path
                    or (None if str(response_payload.get("image_url") or "").strip() else "inline_base64:response")
                ),
                mime_type="image/png" if "image_base64" in response_payload else None,
                provider_source=provider_source,
                media_origin="generated",
                media_status="available" if ("image_url" in response_payload or "image_base64" in response_payload) else "missing",
                media_error_reason=None if ("image_url" in response_payload or "image_base64" in response_payload) else "missing_image_payload",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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
    except asyncio.TimeoutError:
        timeout_message = "Image generation timed out. Please retry."
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=timeout_message,
            model_used=image_model_label,
            success=False,
            image_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{image_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            media=TrackingMedia(
                media_type="image",
                provider_source=provider_source,
                media_origin="generated",
                media_status="failed",
                media_error_reason="timeout",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        logger.warning(
            "API IMAGE TIMEOUT | request_id=%s user=%s timeout_seconds=%s",
            request_id or "unknown",
            user_id,
            IMAGE_ENDPOINT_TIMEOUT_SECONDS,
        )
        payload_response = {"error": timeout_message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=504, content=payload_response)
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="image",
            user_message=user_prompt,
            bot_reply=exc.message,
            model_used=image_model_label,
            success=False,
            image_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{image_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            media=TrackingMedia(
                media_type="image",
                provider_source=provider_source,
                media_origin="generated",
                media_status="failed",
                media_error_reason=exc.message,
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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
        logger.exception("API IMAGE FAILED | request_id=%s user=%s", request_id or "unknown", user_id)
        payload_response = {"error": SAFE_SERVICE_UNAVAILABLE_MESSAGE}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=500, content=payload_response)


@app.post("/video")
@app.post("/api/video")
async def video_endpoint(request: Request, payload: VideoRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    frontend_source = _resolve_frontend_source(request)
    feature_used = "video_generation"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    referral_code = _extract_referral_code(request)
    user_prompt = payload.effective_prompt
    video_model_option = payload.effective_model_option
    video_model_label = _video_model_label(video_model_option)
    video_model_id = _video_model_id_for_option(settings, video_model_option)
    duration_seconds = payload.effective_duration_seconds
    aspect_ratio = payload.effective_aspect_ratio

    logger.info(
        "API VIDEO START | request_id=%s user=%s prompt_len=%s duration=%s aspect_ratio=%s model=%s",
        request_id or "unknown",
        user_id,
        len(user_prompt or ""),
        duration_seconds,
        aspect_ratio,
        video_model_label,
    )
    join_required_message = _video_join_required_text()
    if identity is None:
        payload_response: dict[str, Any] = {"error": join_required_message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=401, content=payload_response)

    if not await _is_video_generation_allowed(identity.telegram_id):
        await _track_api_action(
            identity=identity,
            message_type="video",
            user_message=user_prompt,
            bot_reply=join_required_message,
            model_used=video_model_label,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{video_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            mark_started=True,
            referral_code=referral_code,
        )
        payload_response = {"error": join_required_message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=403, content=payload_response)

    refusal = _maybe_block_sensitive_request(user_prompt, aspect_ratio, str(duration_seconds))
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="video",
            user_message=user_prompt,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=video_model_label,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{video_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        return refusal

    try:
        enhanced_prompt = build_enhanced_video_prompt(
            user_prompt,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
        ) or user_prompt
        result_payload = await asyncio.wait_for(
            _generate_pollinations_video(
                prompt=enhanced_prompt,
                model=video_model_id,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
            ),
            timeout=VIDEO_ENDPOINT_TIMEOUT_SECONDS,
        )
        response_payload: dict[str, Any] = {
            "output": user_prompt,
            "model_label": video_model_label,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
        }
        response_payload.update(result_payload)
        media_url = str(response_payload.get("video_url") or "").strip() or None
        mime_type = str(response_payload.get("video_mime_type") or "").strip() or "video/mp4"
        storage_path: str | None = None
        if media_url and media_url.startswith("/media/"):
            storage_path = f"local_file:{media_url.split('/', maxsplit=2)[-1]}"
        await _track_api_action(
            identity=identity,
            message_type="video",
            user_message=user_prompt,
            bot_reply=str(response_payload.get("output", "Video generated successfully.")),
            model_used=video_model_label,
            success=True,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{video_model_option}",
            conversation_id=conversation_id,
            text_content=str(response_payload.get("output", "Video generated successfully.")),
            media=TrackingMedia(
                media_type="video",
                media_url=media_url,
                storage_path=storage_path,
                mime_type=mime_type,
                provider_source="pollinations",
                media_origin="generated",
                media_status="available" if media_url else "missing",
                media_error_reason=None if media_url else "missing_video_payload",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        return JSONResponse(status_code=200, content=response_payload)
    except asyncio.TimeoutError:
        timeout_message = "Video generation timed out. Please retry."
        await _track_api_action(
            identity=identity,
            message_type="video",
            user_message=user_prompt,
            bot_reply=timeout_message,
            model_used=video_model_label,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{video_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            media=TrackingMedia(
                media_type="video",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason="timeout",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        payload_response: dict[str, Any] = {"error": timeout_message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=504, content=payload_response)
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="video",
            user_message=user_prompt,
            bot_reply=exc.message,
            model_used=video_model_label,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=f"{feature_used}:{video_model_option}",
            conversation_id=conversation_id,
            text_content=user_prompt,
            media=TrackingMedia(
                media_type="video",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason=exc.message,
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        payload_response = {"error": exc.message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload_response)
    except Exception:
        logger.exception("API VIDEO FAILED | request_id=%s user=%s", request_id or "unknown", user_id)
        payload_response = {"error": SAFE_SERVICE_UNAVAILABLE_MESSAGE}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=500, content=payload_response)


@app.post("/vision")
@app.post("/api/vision")
async def vision_endpoint(request: Request, payload: VisionDescribeRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    frontend_source = _resolve_frontend_source(request)
    feature_used = "image_vision"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    referral_code = _extract_referral_code(request)
    compact_image_base64 = "".join((payload.image_base64 or "").split())
    inline_image_url = (
        f"data:image/jpeg;base64,{compact_image_base64}"
        if compact_image_base64 and len(compact_image_base64) <= 23_000
        else None
    )
    uploaded_media_url: str | None = None
    uploaded_storage_path: str | None = None
    upload_media_error: str | None = None
    if compact_image_base64:
        try:
            upload_bytes = _decode_base64_image(compact_image_base64)
            uploaded_media_url, uploaded_storage_path = _persist_image_bytes_to_local_asset(
                upload_bytes,
                prefix="upload",
                mime_type="image/jpeg",
            )
        except BackendError as exc:
            upload_media_error = exc.message
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_message,
            media=TrackingMedia(
                media_type="image",
                media_url=uploaded_media_url or inline_image_url,
                storage_path=uploaded_storage_path or (None if inline_image_url else "inline_upload:truncated"),
                mime_type="image/jpeg",
                provider_source="user",
                media_origin="upload",
                media_status="available" if (uploaded_media_url or inline_image_url) else "missing",
                media_error_reason=(
                    upload_media_error
                    or (None if (uploaded_media_url or inline_image_url) else "image_too_large_for_inline_preview")
                ),
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=output,
            media=TrackingMedia(
                media_type="image",
                media_url=uploaded_media_url or inline_image_url,
                storage_path=uploaded_storage_path or (None if inline_image_url else "inline_upload:truncated"),
                mime_type="image/jpeg",
                provider_source="user",
                media_origin="upload",
                media_status="available" if (uploaded_media_url or inline_image_url) else "missing",
                media_error_reason=(
                    upload_media_error
                    or (None if (uploaded_media_url or inline_image_url) else "image_too_large_for_inline_preview")
                ),
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_message,
            media=TrackingMedia(
                media_type="image",
                media_url=uploaded_media_url or inline_image_url,
                storage_path=uploaded_storage_path or (None if inline_image_url else "inline_upload:truncated"),
                mime_type="image/jpeg",
                provider_source="user",
                media_origin="upload",
                media_status="failed",
                media_error_reason=upload_media_error or exc.message,
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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


@app.post("/gpt-audio")
@app.post("/api/gpt-audio")
async def gpt_audio_endpoint(request: Request, payload: GPTAudioRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    frontend_source = _resolve_frontend_source(request)
    feature_used = "gpt_audio"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    referral_code = _extract_referral_code(request)
    user_prompt = payload.effective_prompt
    logger.info(
        "API GPT AUDIO START | request_id=%s user=%s prompt_len=%s",
        request_id or "unknown",
        user_id,
        len(user_prompt or ""),
    )
    refusal = _maybe_block_sensitive_request(user_prompt)
    if refusal:
        await _track_api_action(
            identity=identity,
            message_type="gpt_audio",
            user_message=user_prompt,
            bot_reply=SAFE_INTERNAL_DETAILS_REFUSAL,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_prompt,
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        logger.info(
            "API GPT AUDIO REFUSED | request_id=%s user=%s",
            request_id or "unknown",
            user_id,
        )
        return refusal

    try:
        enhanced_prompt = (
            "Answer the user request with a clear spoken explanation.\n"
            "Keep it natural, concise, and helpful.\n\n"
            f"User request: {user_prompt}"
        )
        generated = await asyncio.wait_for(
            _generate_pollinations_audio(prompt=enhanced_prompt),
            timeout=GPT_AUDIO_ENDPOINT_TIMEOUT_SECONDS,
        )
        response_payload: dict[str, Any] = {
            "output": "Audio generated successfully.",
            "model_label": GPT_AUDIO_MODEL_LABEL,
        }
        response_payload.update(generated)
        await _track_api_action(
            identity=identity,
            message_type="gpt_audio",
            user_message=user_prompt,
            bot_reply=str(response_payload.get("output", "Audio generated successfully.")),
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=True,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=str(response_payload.get("output", "Audio generated successfully.")),
            media=TrackingMedia(
                media_type="audio",
                mime_type=str(response_payload.get("audio_mime_type") or "audio/mpeg"),
                provider_source="pollinations",
                media_origin="generated",
                media_status="available",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        logger.info(
            "API GPT AUDIO SUCCESS | request_id=%s user=%s audio_mime_type=%s",
            request_id or "unknown",
            user_id,
            response_payload.get("audio_mime_type", ""),
        )
        return JSONResponse(status_code=200, content=response_payload)
    except asyncio.TimeoutError:
        timeout_message = "Audio generation timed out. Please retry."
        await _track_api_action(
            identity=identity,
            message_type="gpt_audio",
            user_message=user_prompt,
            bot_reply=timeout_message,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_prompt,
            media=TrackingMedia(
                media_type="audio",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason="timeout",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        payload_response: dict[str, Any] = {"error": timeout_message}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=504, content=payload_response)
    except BackendError as exc:
        await _track_api_action(
            identity=identity,
            message_type="gpt_audio",
            user_message=user_prompt,
            bot_reply=exc.message,
            model_used=GPT_AUDIO_MODEL_LABEL,
            success=False,
            message_increment=1,
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_prompt,
            media=TrackingMedia(
                media_type="audio",
                provider_source="pollinations",
                media_origin="generated",
                media_status="failed",
                media_error_reason=exc.message,
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
        )
        logger.warning(
            "API GPT AUDIO BACKEND ERROR | request_id=%s user=%s status=%s error=%s",
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
            "API GPT AUDIO FAILED | request_id=%s user=%s error=%s",
            request_id or "unknown",
            user_id,
            exc,
        )
        payload_response = {"error": SAFE_SERVICE_UNAVAILABLE_MESSAGE}
        if request_id:
            payload_response["request_id"] = request_id
        return JSONResponse(status_code=500, content=payload_response)


@app.post("/tts")
@app.post("/api/tts")
async def tts_endpoint(request: Request, payload: TTSRequest) -> JSONResponse:
    request_id = _request_id_from_request(request)
    identity = _resolve_tracking_identity(request, payload)
    user_id = identity.telegram_id if identity else "unknown"
    settings = get_settings()
    frontend_source = _resolve_frontend_source(request)
    feature_used = "text_to_speech"
    conversation_id = _extract_conversation_id(request, identity, feature_used)
    referral_code = _extract_referral_code(request)
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_text,
            mark_started=bool(identity),
            referral_code=referral_code,
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=str(response_payload.get("output", "Speech generated successfully.")),
            media=TrackingMedia(
                media_type="audio",
                mime_type=str(response_payload.get("audio_mime_type") or "audio/mpeg"),
                provider_source="nvidia",
                media_origin="generated",
                media_status="available",
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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
            frontend_source=frontend_source,
            feature_used=feature_used,
            conversation_id=conversation_id,
            text_content=user_text,
            media=TrackingMedia(
                media_type="audio",
                provider_source="nvidia",
                media_origin="generated",
                media_status="failed",
                media_error_reason=exc.message,
            ),
            mark_started=bool(identity),
            referral_code=referral_code,
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
