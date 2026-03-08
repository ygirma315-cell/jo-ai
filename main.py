from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import re
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


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=32000)


class CodeRequest(ChatRequest):
    code_file_name: str | None = Field(default=None, max_length=240)
    code_file_base64: str | None = Field(default=None, max_length=4_000_000)


class ImageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

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


class PromptRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=32000)
    prompt_type: str | None = Field(default=None, max_length=120)

    @property
    def effective_prompt_type(self) -> str:
        return self.prompt_type or "general"


class AITextRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mode: TextMode = "chat"
    message: str = Field(min_length=1, max_length=32000)
    prompt_type: str | None = Field(default=None, max_length=120)
    code_file_name: str | None = Field(default=None, max_length=240)
    code_file_base64: str | None = Field(default=None, max_length=4_000_000)

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
        api_key=settings.image_api_key or settings.nvidia_api_key or settings.ai_api_key,
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
    mode: TextMode,
    message: str,
    prompt_type: str | None = None,
    code_file_name: str | None = None,
    code_file_base64: str | None = None,
) -> JSONResponse:
    refusal = _maybe_block_sensitive_request(message, prompt_type)
    if refusal:
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
        return JSONResponse(status_code=200, content=payload)
    except BackendError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.post("/ai")
@app.post("/api/ai")
async def ai_endpoint(payload: AITextRequest) -> JSONResponse:
    return await _handle_text_mode_request(
        mode=payload.mode,
        message=payload.message,
        prompt_type=payload.prompt_type,
        code_file_name=payload.code_file_name,
        code_file_base64=payload.code_file_base64,
    )


@app.post("/chat")
@app.post("/api/chat")
async def chat_endpoint(payload: ChatRequest) -> JSONResponse:
    return await _handle_text_mode_request(mode="chat", message=payload.message)


@app.post("/code")
@app.post("/api/code")
async def code_endpoint(payload: CodeRequest) -> JSONResponse:
    return await _handle_text_mode_request(
        mode="code",
        message=payload.message,
        code_file_name=payload.code_file_name,
        code_file_base64=payload.code_file_base64,
    )


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
    refusal = _maybe_block_sensitive_request(payload.effective_prompt, payload.image_type, payload.ratio)
    if refusal:
        return refusal
    try:
        prompt = payload.effective_prompt
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
        return JSONResponse(status_code=200, content=response_payload)
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
