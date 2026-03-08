from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import time
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import uvicorn
from aiogram.types import Update
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
from bot.services.ai_service import AIServiceError, ChatService, ImageGenerationService
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


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=8000)


class ImageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str | None = Field(default=None, max_length=4000)
    message: str | None = Field(default=None, max_length=4000)
    size: str = Field(default="1024x1024", pattern=r"^\d+x\d+$")

    @model_validator(mode="after")
    def _validate_prompt(self) -> "ImageRequest":
        if not self.prompt and not self.message:
            raise ValueError("Either 'prompt' or 'message' must be provided.")
        return self

    @property
    def effective_prompt(self) -> str:
        return self.prompt or self.message or ""


class PromptRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=8000)
    prompt_type: str | None = Field(default=None, max_length=120)

    @property
    def effective_prompt_type(self) -> str:
        return self.prompt_type or "general"


class AITextRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mode: Literal["chat", "code", "research", "prompt"] = "chat"
    message: str = Field(min_length=1, max_length=8000)
    prompt_type: str | None = Field(default=None, max_length=120)

    @property
    def effective_prompt_type(self) -> str:
        return self.prompt_type or "general"


class VisionDescribeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str | None = Field(default=None, max_length=2000)
    image_base64: str = Field(min_length=1, max_length=15_000_000)

    @property
    def effective_message(self) -> str:
        return self.message or "Describe this image."


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
        api_key=settings.nvidia_api_key or settings.ai_api_key,
        model=settings.image_model,
        base_url=settings.ai_base_url,
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


async def _run_text_mode_completion(message: str, mode: Literal["chat", "code", "research", "prompt"], prompt_type: str | None = None) -> str:
    settings = get_settings()
    effective_api_key = settings.nvidia_api_key or settings.ai_api_key
    if not effective_api_key:
        raise _safe_service_error(status_code=503)

    request_message = _compose_prompt_request(prompt_type or "general", message) if mode == "prompt" else message
    model_override = settings.code_model if mode == "code" else settings.nvidia_chat_model

    try:
        return await _chat_service().generate_reply(
            request_message,
            history=[],
            mode=mode,
            model_override=model_override,
            api_key_override=effective_api_key,
            thinking=False,
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


async def _generate_image(prompt: str, size: str) -> str:
    try:
        raw_bytes = await _image_service().generate_image(prompt, size=size)
        return base64.b64encode(raw_bytes).decode("utf-8")
    except AIServiceError as exc:
        logger.warning("Image generation failed.", exc_info=True)
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
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
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
    settings.require_valid()

    role = _read_env("PROCESS_ROLE") or "web"
    app.state.started_at = time.time()
    logger.info("API STARTED | version=%s", VERSION)
    logger.info("PROCESS=%s ENTRYPOINT=main.py VERSION=%s", role, VERSION)

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
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    message = first_error.get("msg", "Invalid request payload.")
    return JSONResponse(status_code=422, content={"error": message})


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
    mode: Literal["chat", "code", "research", "prompt"],
    message: str,
    prompt_type: str | None = None,
) -> JSONResponse:
    refusal = _maybe_block_sensitive_request(message, prompt_type)
    if refusal:
        return refusal
    try:
        output = await _run_text_mode_completion(message, mode=mode, prompt_type=prompt_type)
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/ai")
@app.post("/api/ai")
async def ai_endpoint(payload: AITextRequest) -> JSONResponse:
    return await _handle_text_mode_request(
        mode=payload.mode,
        message=payload.message,
        prompt_type=payload.prompt_type,
    )


@app.post("/chat")
@app.post("/api/chat")
async def chat_endpoint(payload: ChatRequest) -> JSONResponse:
    return await _handle_text_mode_request(mode="chat", message=payload.message)


@app.post("/code")
@app.post("/api/code")
async def code_endpoint(payload: ChatRequest) -> JSONResponse:
    return await _handle_text_mode_request(mode="code", message=payload.message)


@app.post("/research")
@app.post("/api/research")
async def research_endpoint(payload: ChatRequest) -> JSONResponse:
    return await _handle_text_mode_request(mode="research", message=payload.message)


@app.post("/prompt")
@app.post("/api/prompt")
async def prompt_endpoint(payload: PromptRequest) -> JSONResponse:
    return await _handle_text_mode_request(
        mode="prompt",
        message=payload.message,
        prompt_type=payload.effective_prompt_type,
    )


@app.post("/image")
@app.post("/api/image")
async def image_endpoint(payload: ImageRequest) -> JSONResponse:
    refusal = _maybe_block_sensitive_request(payload.effective_prompt)
    if refusal:
        return refusal
    try:
        image_base64 = await _generate_image(payload.effective_prompt, payload.size)
        return JSONResponse(
            status_code=200,
            content={
                "output": "Image generated successfully.",
                "image_base64": image_base64,
            },
        )
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/vision")
@app.post("/api/vision")
async def vision_endpoint(payload: VisionDescribeRequest) -> JSONResponse:
    refusal = _maybe_block_sensitive_request(payload.effective_message)
    if refusal:
        return refusal
    try:
        output = await _describe_image_with_vision(payload.effective_message, payload.image_base64)
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


if __name__ == "__main__":
    host = _read_env("HOST") or "0.0.0.0"
    try:
        port = int(_read_env("PORT") or "8000")
    except ValueError:
        port = 8000
    uvicorn.run("main:app", host=host, port=port)
