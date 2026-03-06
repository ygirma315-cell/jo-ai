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
from typing import Any
from urllib.parse import urlparse

import requests
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
from version import VERSION

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


class KimiImageDescribeRequest(BaseModel):
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


def _extract_provider_error(payload: object) -> str | None:
    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error_obj, str) and error_obj.strip():
            return error_obj.strip()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return None


def _provider_post(path: str, payload: dict[str, Any], api_key_override: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    api_key = (api_key_override or settings.ai_api_key or "").strip()
    if not api_key:
        raise BackendError("AI API key is missing. Set AI_API_KEY or NVIDIA_API_KEY in the environment.", status_code=500)

    url = f"{settings.ai_base_url}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=settings.request_timeout_seconds)
    except requests.RequestException as exc:
        logger.warning("AI provider request failed for %s: %s", path, exc)
        raise BackendError("Failed to reach AI provider.", status_code=502) from exc

    try:
        body: object = response.json()
    except json.JSONDecodeError:
        body = {}

    if response.status_code >= 400:
        message = _extract_provider_error(body) or "AI provider rejected the request."
        raise BackendError(message, status_code=502)

    if not isinstance(body, dict):
        raise BackendError("AI provider returned an invalid response.")
    return body


def _extract_text_response(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise BackendError("AI provider returned no response choices.")

    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        raise BackendError("AI provider returned an invalid message format.")

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks)

    raise BackendError("AI provider returned an empty answer.")


def _chat_completion(user_message: str, mode: str) -> str:
    settings = get_settings()
    model = settings.code_model if mode == "code" else settings.nvidia_chat_model

    prompts = {
        "chat": "You are a concise, practical assistant.",
        "code": "You are a senior software engineer. Return working code first, then brief run notes.",
        "research": (
            "You are a research assistant. Structure output with Summary, Details, Risks/Tradeoffs, and Next Steps."
        ),
        "prompt": "You are a prompt engineer. Return one optimized prompt only.",
    }
    system_prompt = prompts.get(mode, prompts["chat"])
    max_tokens = 400
    if mode == "code":
        max_tokens = 800
    elif mode == "research":
        max_tokens = 900
    elif mode == "prompt":
        max_tokens = 500

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }

    data = _provider_post("/chat/completions", payload)
    return _extract_text_response(data)


def _compose_prompt_request(prompt_type: str, message: str) -> str:
    return (
        f"Prompt type: {prompt_type}\n"
        f"User requirements:\n{message}\n\n"
        "Return exactly one optimized prompt that is specific and reusable."
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


def _describe_image_with_kimi(message: str, image_base64: str) -> str:
    settings = get_settings()
    image_bytes = _decode_base64_image(image_base64)
    image_payload = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": settings.kimi_model,
        "messages": [
            {
                "role": "system",
                "content": "Describe visible image content clearly in 2-5 concise sentences.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": message.strip() or "Describe this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_payload}"}},
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 350,
    }

    data = _provider_post("/chat/completions", payload, api_key_override=settings.kimi_api_key)
    return _extract_text_response(data)


def _download_image_as_base64(url: str) -> str:
    settings = get_settings()
    try:
        response = requests.get(url, timeout=settings.request_timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BackendError("Generated image URL could not be downloaded.") from exc
    return base64.b64encode(response.content).decode("utf-8")


def _generate_image(prompt: str, size: str) -> str:
    settings = get_settings()
    payload = {
        "model": settings.image_model,
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json",
    }

    data = _provider_post("/images/generations", payload)
    image_data = data.get("data")
    if not isinstance(image_data, list) or not image_data:
        raise BackendError("AI provider returned no image data.")

    first_image = image_data[0] if isinstance(image_data[0], dict) else {}
    b64_image = first_image.get("b64_json")
    if isinstance(b64_image, str) and b64_image.strip():
        return b64_image.strip()

    image_url = first_image.get("url")
    if isinstance(image_url, str) and image_url.strip():
        return _download_image_as_base64(image_url.strip())

    raise BackendError("AI provider did not return a usable image.")


def _get_bot_runtime() -> BotRuntime | None:
    runtime = getattr(app.state, "bot_runtime", None)
    return runtime if isinstance(runtime, BotRuntime) else None


def _uptime_seconds() -> float:
    started_at = getattr(app.state, "started_at", None)
    if not isinstance(started_at, (int, float)):
        return 0.0
    return max(0.0, time.time() - float(started_at))


def _deployment_info() -> dict[str, Any]:
    payload = {
        "provider": "render" if _read_env("RENDER") or _read_env("RENDER_SERVICE_NAME") else "local",
        "repo": _read_env("RENDER_GIT_REPO_SLUG") or _read_env("GITHUB_REPOSITORY"),
        "branch": _read_env("RENDER_GIT_BRANCH") or _read_env("GITHUB_REF_NAME"),
        "commit": _read_env("RENDER_GIT_COMMIT") or _read_env("GITHUB_SHA"),
        "service_name": _read_env("RENDER_SERVICE_NAME"),
    }
    return {key: value for key, value in payload.items() if value}


def _health_checks() -> dict[str, Any]:
    settings = get_settings()
    runtime = _get_bot_runtime()
    telegram_status = "ok" if runtime and runtime.telegram_ready else "starting"
    if runtime and runtime.last_startup_error:
        telegram_status = "degraded"

    return {
        "config": {
            "status": "ok" if not settings.validation_errors else "error",
            "warnings": list(settings.validation_warnings),
        },
        "telegram": {
            "status": telegram_status,
            "webhook_configured": runtime.webhook_configured if runtime else False,
            "menu_button_configured": runtime.menu_button_configured if runtime else False,
            "last_error": runtime.last_startup_error if runtime else None,
        },
    }


def _service_info() -> dict[str, Any]:
    settings = get_settings()
    runtime = _get_bot_runtime()
    payload = {
        "process_role": _read_env("PROCESS_ROLE") or "web",
        "public_base_url": settings.public_base_url,
        "miniapp_url": settings.miniapp_url,
        "webhook_url": settings.telegram_webhook_url,
        "telegram_ready": runtime.telegram_ready if runtime else False,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _runtime_info_payload() -> dict[str, Any]:
    settings = get_settings()
    return build_runtime_info(
        chat_model=settings.nvidia_chat_model,
        code_model=settings.code_model,
        image_model=settings.image_model,
        deepseek_model=settings.deepseek_model,
        kimi_model=settings.kimi_model,
        deploy=_deployment_info(),
        service=_service_info(),
        checks=_health_checks(),
        uptime_seconds=_uptime_seconds(),
    )


app = FastAPI(title="JO AI Backend + Telegram Bot", version=VERSION)
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
    logger.info("[RENDER] PROCESS=%s ENTRYPOINT=main.py VERSION=%s", role, VERSION)

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
    settings = get_settings()
    return {
        "ok": True,
        "service": "jo-ai-backend",
        "version": VERSION,
        "miniapp_url": settings.miniapp_url,
        "health_url": "/api/health",
        "webhook_url": "/telegram/webhook",
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    return _runtime_info_payload()


@app.get("/uptime")
@app.get("/api/uptime")
def uptime() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": round(_uptime_seconds(), 2),
    }


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


@app.post("/chat")
@app.post("/api/chat")
def chat_endpoint(payload: ChatRequest) -> JSONResponse:
    try:
        output = _chat_completion(payload.message, mode="chat")
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/code")
@app.post("/api/code")
def code_endpoint(payload: ChatRequest) -> JSONResponse:
    try:
        output = _chat_completion(payload.message, mode="code")
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/research")
@app.post("/api/research")
def research_endpoint(payload: ChatRequest) -> JSONResponse:
    try:
        output = _chat_completion(payload.message, mode="research")
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/prompt")
@app.post("/api/prompt")
def prompt_endpoint(payload: PromptRequest) -> JSONResponse:
    try:
        composed = _compose_prompt_request(payload.effective_prompt_type, payload.message)
        output = _chat_completion(composed, mode="prompt")
        return JSONResponse(status_code=200, content={"output": output})
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/image")
@app.post("/api/image")
def image_endpoint(payload: ImageRequest) -> JSONResponse:
    try:
        image_base64 = _generate_image(payload.effective_prompt, payload.size)
        return JSONResponse(
            status_code=200,
            content={
                "output": "Image generated successfully.",
                "image_base64": image_base64,
            },
        )
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/kimi_image_describer")
@app.post("/api/kimi_image_describer")
def kimi_image_describer_endpoint(payload: KimiImageDescribeRequest) -> JSONResponse:
    try:
        output = _describe_image_with_kimi(payload.effective_message, payload.image_base64)
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
