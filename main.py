from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import socket
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from version import VERSION

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Settings:
    ai_api_key: str
    ai_base_url: str
    chat_model: str
    code_model: str
    image_model: str
    kimi_api_key: str
    kimi_model: str
    timeout_seconds: int


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    timeout_raw = _read_env("REQUEST_TIMEOUT_SECONDS") or "30"
    try:
        timeout_seconds = max(5, int(timeout_raw))
    except ValueError:
        timeout_seconds = 30

    ai_api_key = _read_env("AI_API_KEY") or _read_env("NVIDIA_API_KEY") or _read_env("OPENAI_API_KEY")
    ai_base_url = _read_env("AI_BASE_URL") or "https://integrate.api.nvidia.com/v1"
    ai_base_url = ai_base_url.rstrip("/")

    chat_model = _read_env("CHAT_MODEL") or _read_env("NVIDIA_CHAT_MODEL") or "meta/llama-3.1-8b-instruct"
    code_model = _read_env("CODE_MODEL") or chat_model
    image_model = _read_env("IMAGE_MODEL") or "black-forest-labs/flux.1-dev"
    kimi_api_key = _read_env("KIMI_API_KEY") or ai_api_key
    kimi_model = _read_env("KIMI_MODEL") or "moonshotai/kimi-k2.5"

    return Settings(
        ai_api_key=ai_api_key,
        ai_base_url=ai_base_url,
        chat_model=chat_model,
        code_model=code_model,
        image_model=image_model,
        kimi_api_key=kimi_api_key,
        kimi_model=kimi_model,
        timeout_seconds=timeout_seconds,
    )


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
    api_key = (api_key_override or settings.ai_api_key).strip()
    if not api_key:
        raise BackendError("AI API key is missing. Set AI_API_KEY (or NVIDIA_API_KEY) in .env.", status_code=500)

    url = f"{settings.ai_base_url}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=settings.timeout_seconds)
    except requests.RequestException:
        raise BackendError("Failed to reach AI provider.", status_code=502)

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
    model = settings.code_model if mode == "code" else settings.chat_model

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
    except (binascii.Error, ValueError):
        raise BackendError("Invalid base64 image payload.", status_code=400)


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
        response = requests.get(url, timeout=settings.timeout_seconds)
        response.raise_for_status()
    except requests.RequestException:
        raise BackendError("Generated image URL could not be downloaded.")
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


def _allowed_origins() -> list[str]:
    raw = _read_env("ALLOWED_ORIGINS") or "*"
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


def _parse_port(raw_port: str | None, fallback: int = 8000) -> int:
    try:
        return int((raw_port or str(fallback)).strip())
    except (TypeError, ValueError):
        return fallback


def _is_port_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _find_open_port(start_port: int = 8000, host: str = "0.0.0.0", max_attempts: int = 100) -> int:
    first_port = max(1, start_port)
    last_port = min(65535, first_port + max_attempts)

    for port in range(first_port, last_port + 1):
        if _is_port_free(port, host=host):
            return port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


app = FastAPI(title="Telegram Bot + Miniapp Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_log() -> None:
    role = _read_env("PROCESS_ROLE") or "web"
    process_message = f"[RENDER] PROCESS={role} ENTRYPOINT=main.py VERSION={VERSION}"
    print(process_message, flush=True)
    logger.info(process_message)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    message = first_error.get("msg", "Invalid request payload.")
    return JSONResponse(status_code=422, content={"error": message})


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


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
    host = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    preferred_port = _parse_port(os.getenv("PORT"), fallback=8000)
    selected_port = _find_open_port(start_port=preferred_port, host=host)
    print(f"Starting FastAPI server on {host}:{selected_port}")
    uvicorn.run("main:app", host=host, port=selected_port)
