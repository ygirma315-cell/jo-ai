from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
from typing import Literal

import aiohttp


class AIServiceError(RuntimeError):
    pass


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_CHAT_MODEL = "meta/llama-3.1-8b-instruct"
FALLBACK_CHAT_MODEL = "meta/llama-3.1-8b-instruct"
DEFAULT_IMAGE_MODEL = "black-forest-labs/flux.1-dev"

# Backward-compatible alias for existing imports.
OpenAIServiceError = AIServiceError


@dataclass
class ChatService:
    api_key: str | None = None
    model: str = DEFAULT_CHAT_MODEL

    async def generate_reply(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        mode: Literal["chat", "code", "research", "prompt", "image_prompt", "image_describe"] = "chat",
        model_override: str | None = None,
        api_key_override: str | None = None,
        thinking: bool = False,
    ) -> str:
        effective_api_key = (api_key_override or self.api_key or "").strip() or None
        if not effective_api_key:
            raise AIServiceError("Missing NVIDIA_API_KEY environment variable.")

        messages: list[dict[str, str]] = [{"role": "system", "content": _system_instruction_for_mode(mode)}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": _enhance_user_prompt(mode, user_message)})

        selected_model = (model_override or self.model).strip()
        payload = _build_chat_payload(model=selected_model, messages=messages, mode=mode, thinking=thinking)
        try:
            data = await _post_nvidia_json(effective_api_key, "/chat/completions", payload)
        except AIServiceError as exc:
            if selected_model != FALLBACK_CHAT_MODEL and _is_timeout_error(str(exc)):
                fallback_payload = _build_chat_payload(
                    model=FALLBACK_CHAT_MODEL, messages=messages, mode=mode, thinking=False
                )
                data = await _post_nvidia_json(effective_api_key, "/chat/completions", fallback_payload)
            else:
                raise
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIServiceError("NVIDIA API did not return any chat choices.")

        message = choices[0].get("message", {})
        content = _extract_message_content(message)
        if content:
            return content

        raise AIServiceError("NVIDIA API returned an empty chat response.")

    async def generate_reply_with_image(
        self,
        user_message: str,
        image_bytes: bytes,
        mode: Literal["research", "image_prompt", "image_describe"] = "image_describe",
        model_override: str | None = None,
        api_key_override: str | None = None,
        thinking: bool = False,
    ) -> str:
        effective_api_key = (api_key_override or self.api_key or "").strip() or None
        if not effective_api_key:
            raise AIServiceError("Missing API key for image description.")

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        selected_model = (model_override or self.model).strip()
        messages: list[dict[str, object]] = [
            {"role": "system", "content": _system_instruction_for_mode(mode)},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _enhance_user_prompt(mode, user_message)},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            },
        ]
        payload = _build_chat_payload(model=selected_model, messages=messages, mode=mode, thinking=thinking)
        data = await _post_nvidia_json(effective_api_key, "/chat/completions", payload, timeout_seconds=40)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIServiceError("API did not return image description choices.")
        message = choices[0].get("message", {})
        content = _extract_message_content(message)
        if content:
            return content
        raise AIServiceError("API returned empty image description.")


@dataclass
class ImageGenerationService:
    api_key: str | None = None
    model: str = DEFAULT_IMAGE_MODEL

    async def generate_image(self, prompt: str) -> bytes:
        if not self.api_key:
            raise AIServiceError("Missing NVIDIA_API_KEY environment variable.")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": "1024x1024",
            "response_format": "b64_json",
        }
        data = await _post_nvidia_json(self.api_key, "/images/generations", payload)
        image_data = data.get("data")
        if not isinstance(image_data, list) or not image_data:
            raise AIServiceError("NVIDIA API did not return image output.")

        first_item = image_data[0] if isinstance(image_data[0], dict) else {}
        b64_payload = first_item.get("b64_json")
        if isinstance(b64_payload, str) and b64_payload:
            try:
                return base64.b64decode(b64_payload)
            except ValueError as exc:
                raise AIServiceError("Failed to decode generated image bytes.") from exc

        image_url = first_item.get("url")
        if isinstance(image_url, str) and image_url.strip():
            return await _download_image_bytes(image_url.strip())

        raise AIServiceError("NVIDIA image response did not include image bytes.")


@dataclass
class VideoGenerationService:
    api_key: str | None = None


async def _post_nvidia_json(
    api_key: str, path: str, payload: dict[str, object], timeout_seconds: int = 28
) -> dict[str, object]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{NVIDIA_BASE_URL}{path}", headers=headers, json=payload) as response:
                body = await response.text()
    except asyncio.TimeoutError as exc:
        raise AIServiceError("NVIDIA request timed out.") from exc
    except aiohttp.ClientError as exc:
        raise AIServiceError(f"NVIDIA network error: {exc}") from exc

    if response.status >= 400:
        message = _extract_api_error(body)
        if response.status == 404 and path == "/images/generations":
            raise AIServiceError(
                "NVIDIA Integrate API does not expose /v1/images/generations for this key/endpoint."
            )
        raise AIServiceError(f"NVIDIA API error ({response.status}): {message}")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AIServiceError("NVIDIA API returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise AIServiceError("NVIDIA API returned an unexpected response format.")
    return parsed


def _extract_api_error(raw_text: str) -> str:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text[:300] or "Unknown error."

    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        detail = parsed.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return raw_text[:300] or "Unknown error."


def _extract_message_content(message: object) -> str | None:
    if not isinstance(message, dict):
        return None

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

    return None


def _build_chat_payload(
    model: str,
    messages: list[dict[str, object]],
    mode: Literal["chat", "code", "research", "prompt", "image_prompt", "image_describe"],
    thinking: bool = False,
) -> dict[str, object]:
    max_tokens_map = {
        "chat": 220,
        "code": 420,
        "research": 650,
        "prompt": 260,
        "image_prompt": 260,
        "image_describe": 180,
    }
    max_tokens = max_tokens_map.get(mode, 220)
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.4,
        "top_p": 0.95,
        "stream": False,
    }
    if thinking:
        payload["chat_template_kwargs"] = {"thinking": True}
    return payload


def _is_timeout_error(error_text: str) -> bool:
    lower = error_text.lower()
    return "timed out" in lower or "timeout" in lower


async def _download_image_bytes(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=35)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise AIServiceError(f"Image download failed with status {response.status}.")
                return await response.read()
    except asyncio.TimeoutError as exc:
        raise AIServiceError("Image download timed out.") from exc
    except aiohttp.ClientError as exc:
        raise AIServiceError(f"Image download failed: {exc}") from exc


def _system_instruction_for_mode(mode: Literal["chat", "code", "research", "prompt", "image_prompt", "image_describe"]) -> str:
    if mode == "code":
        return (
            "You are JO AI Code Generator.\n"
            "Role: produce practical, correct code.\n"
            "Task: answer with executable code first, then short notes.\n"
            "Format:\n"
            "1) Language and dependencies\n"
            "2) Code block\n"
            "3) How to run\n"
            "Keep output concise and production-minded."
        )
    if mode == "research":
        return (
            "You are JO AI Research Assistant.\n"
            "Role: provide detailed, structured explanations.\n"
            "Task: break down the answer into key points, evidence, and actionable conclusions.\n"
            "Format: Summary, Details, Risks/Tradeoffs, Next Steps.\n"
            "If uncertain, clearly state assumptions."
        )
    if mode == "prompt":
        return (
            "You are JO AI Prompt Engineer.\n"
            "Role: generate high-quality prompts for external AI tools.\n"
            "Task: return one optimized prompt based on user intent and constraints.\n"
            "Requirements:\n"
            "- Include role, objective, constraints, style/tone, and output format.\n"
            "- Be specific, not generic.\n"
            "- Avoid extra commentary outside the final prompt.\n"
            "Output format: 'Optimized Prompt:' followed by the prompt text."
        )
    if mode == "image_prompt":
        return (
            "You are JO AI Image Prompt Engineer.\n"
            "Role: create production-grade prompts for image generation models.\n"
            "Task: output one optimized image prompt only.\n"
            "Must include: subject details, lighting, environment, style, composition, quality tags.\n"
            "Output format: 'Optimized Prompt:' followed by one single-line prompt."
        )
    if mode == "image_describe":
        return (
            "You are Kimi Image Describer.\n"
            "Task: quickly describe what is visible in the image in 2-4 short sentences.\n"
            "If unclear, say you are not sure and suggest sending a clearer image.\n"
            "Keep the answer concise and direct."
        )
    return (
        "You are JO AI Assistant.\n"
        "Role: helpful and concise general assistant.\n"
        "Task: answer clearly and directly.\n"
        "Format: short answer with practical steps when useful."
    )


def _enhance_user_prompt(
    mode: Literal["chat", "code", "research", "prompt", "image_prompt", "image_describe"], raw_input: str
) -> str:
    text = raw_input.strip()
    if mode == "chat":
        return f"User request:\n{text}\n\nRespond clearly and directly."
    if mode == "code":
        return (
            f"Code request:\n{text}\n\n"
            "Return practical code first. Include brief run notes."
        )
    if mode == "research":
        return (
            f"Research request:\n{text}\n\n"
            "Provide structured and evidence-aware analysis."
        )
    if mode == "prompt":
        return (
            f"Prompt generation request:\n{text}\n\n"
            "Return one optimized prompt that is specific and reusable."
        )
    if mode == "image_describe":
        return f"Image description request:\n{text}\n\nDescribe only what is visible."
    return (
        f"Image prompt request:\n{text}\n\n"
        "Return one high-quality image prompt with lighting, environment, style and quality tags."
    )
