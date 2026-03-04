from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Literal

from aiohttp import web
from dotenv import load_dotenv

# Ensure project root is importable when running `python miniapp/server.py`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from bot.services.ai_service import AIServiceError, ChatService, ImageGenerationService  # noqa: E402


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


def _chat_service() -> ChatService:
    return ChatService(
        api_key=os.getenv("NVIDIA_API_KEY", "").strip() or None,
        model=os.getenv("NVIDIA_CHAT_MODEL", "meta/llama-3.1-8b-instruct").strip(),
    )


def _image_service() -> ImageGenerationService:
    return ImageGenerationService(
        api_key=os.getenv("NVIDIA_API_KEY", "").strip() or None,
    )


def _profile_options(payload: dict[str, object]) -> dict[str, object]:
    profile_raw = payload.get("model_profile")
    profile = profile_raw.strip() if isinstance(profile_raw, str) else "default"
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-ai/deepseek-v3.2").strip()
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or None

    if profile == "deepseek_thinking":
        return {
            "model_override": deepseek_model,
            "api_key_override": deepseek_api_key,
            "thinking": True,
        }
    if profile == "deepseek_reasoning":
        return {
            "model_override": deepseek_model,
            "api_key_override": deepseek_api_key,
            "thinking": False,
        }
    return {
        "model_override": deepseek_model,
        "api_key_override": deepseek_api_key,
        "thinking": False,
    }


async def _parse_json(request: web.Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text=json.dumps({"error": "Invalid JSON payload."})) from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text=json.dumps({"error": "JSON object required."}))
    return payload


def _extract_text(payload: dict[str, object], key: str = "message") -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise web.HTTPBadRequest(text=json.dumps({"error": f"'{key}' must be a non-empty string."}))
    return value.strip()


async def _handle_mode(request: web.Request, mode: Literal["chat", "code", "research", "prompt"]) -> web.Response:
    payload = await _parse_json(request)
    message = _extract_text(payload)
    profile_options = _profile_options(payload)
    service = _chat_service()
    try:
        output = await service.generate_reply(
            message,
            history=[],
            mode=mode,
            model_override=profile_options.get("model_override"),  # type: ignore[arg-type]
            api_key_override=profile_options.get("api_key_override"),  # type: ignore[arg-type]
            thinking=bool(profile_options.get("thinking", False)),
        )
    except AIServiceError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "Request timed out."}, status=504)
    except Exception:
        return web.json_response({"error": "Unexpected server error."}, status=500)
    return web.json_response({"output": output})


async def chat_handler(request: web.Request) -> web.Response:
    return await _handle_mode(request, "chat")


async def code_handler(request: web.Request) -> web.Response:
    return await _handle_mode(request, "code")


async def research_handler(request: web.Request) -> web.Response:
    return await _handle_mode(request, "research")


async def prompt_handler(request: web.Request) -> web.Response:
    payload = await _parse_json(request)
    prompt_type = _extract_text(payload, key="prompt_type")
    message = _extract_text(payload, key="message")
    profile_options = _profile_options(payload)
    service = _chat_service()
    composed = (
        f"Prompt type: {prompt_type}\n"
        f"User goal/details: {message}\n"
        "Generate one optimized prompt."
    )
    try:
        output = await service.generate_reply(
            composed,
            history=[],
            mode="prompt",
            model_override=profile_options.get("model_override"),  # type: ignore[arg-type]
            api_key_override=profile_options.get("api_key_override"),  # type: ignore[arg-type]
            thinking=bool(profile_options.get("thinking", False)),
        )
    except AIServiceError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "Request timed out."}, status=504)
    except Exception:
        return web.json_response({"error": "Unexpected server error."}, status=500)
    return web.json_response({"output": output})


async def image_handler(request: web.Request) -> web.Response:
    payload = await _parse_json(request)
    image_type = _extract_text(payload, key="image_type")
    message = _extract_text(payload, key="message")
    profile_options = _profile_options(payload)
    chat_service = _chat_service()
    image_service = _image_service()

    style_hints = {
        "realistic": "photorealistic, natural textures, realistic camera lens, ultra detailed",
        "ai_art": "digital art, stylized illustration, painterly texture, artistic composition",
        "anime": "anime style, clean line art, expressive characters, vibrant colors",
        "cyberpunk": "cyberpunk, neon lighting, futuristic city, rain reflections, cinematic mood",
        "logo_icon": "minimal clean logo design, centered icon, vector style, brand-ready composition",
        "render_3d": "3D render, physically based materials, global illumination, high detail",
        "concept_art": "concept art, environment storytelling, dramatic composition, matte painting quality",
    }
    style_hint = style_hints.get(image_type, style_hints["realistic"])

    composed = (
        f"Image type: {image_type}\n"
        f"Style hints: {style_hint}\n"
        f"User description: {message}\n"
        "Generate one optimized image prompt with subject detail, lighting, environment, style and quality tags."
    )
    try:
        optimized = await chat_service.generate_reply(
            composed,
            history=[],
            mode="image_prompt",
            model_override=profile_options.get("model_override"),  # type: ignore[arg-type]
            api_key_override=profile_options.get("api_key_override"),  # type: ignore[arg-type]
            thinking=bool(profile_options.get("thinking", False)),
        )
    except AIServiceError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "Request timed out while optimizing prompt."}, status=504)
    except Exception:
        return web.json_response({"error": "Unexpected server error during prompt optimization."}, status=500)

    cleaned = optimized.replace("Optimized Prompt:", "").strip() or optimized.strip()
    try:
        image_bytes = await image_service.generate_image(cleaned)
    except AIServiceError as exc:
        return web.json_response(
            {
                "output": f"Image API unavailable. Use this optimized prompt:\n{cleaned}",
                "warning": str(exc),
            },
            status=200,
        )
    except asyncio.TimeoutError:
        return web.json_response(
            {
                "output": f"Image generation timed out. Use this optimized prompt:\n{cleaned}",
            },
            status=200,
        )
    except Exception:
        return web.json_response({"error": "Unexpected image generation error."}, status=500)

    import base64

    return web.json_response(
        {
            "output": f"Optimized prompt used:\n{cleaned}",
            "image_base64": base64.b64encode(image_bytes).decode("utf-8"),
        }
    )


async def kimi_image_describer_handler(request: web.Request) -> web.Response:
    payload = await _parse_json(request)
    message = payload.get("message")
    user_text = message.strip() if isinstance(message, str) and message.strip() else "Describe this image."
    image_raw = payload.get("image_base64")
    if not isinstance(image_raw, str) or not image_raw.strip():
        return web.json_response({"error": "'image_base64' must be a non-empty string."}, status=400)

    kimi_model = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5").strip()
    kimi_api_key = os.getenv("KIMI_API_KEY", "").strip() or None
    service = _chat_service()
    try:
        import base64

        image_bytes = base64.b64decode(image_raw.strip())
    except Exception:
        return web.json_response({"error": "Invalid base64 image payload."}, status=400)

    try:
        output = await service.generate_reply_with_image(
            user_text,
            image_bytes,
            mode="image_describe",
            model_override=kimi_model,
            api_key_override=kimi_api_key,
            thinking=False,
        )
    except AIServiceError as exc:
        text = str(exc).lower()
        if "empty image description" in text or "did not return image description choices" in text:
            return web.json_response(
                {"output": "I couldn't clearly understand this image. Please try another image."},
                status=200,
            )
        return web.json_response(
            {"error": "Kimi image describer is temporarily unavailable or timed out. Please try again shortly."},
            status=502,
        )
    except Exception:
        return web.json_response({"error": "Unexpected server error."}, status=500)
    return web.json_response({"output": output})


async def health_handler(request: web.Request) -> web.Response:
    _ = request
    return web.json_response({"ok": True})


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


def create_app() -> web.Application:
    _load_env()
    app = web.Application(middlewares=[cors_middleware], client_max_size=10 * 1024**2)
    app.router.add_get("/api/health", health_handler)
    app.router.add_post("/api/chat", chat_handler)
    app.router.add_post("/api/code", code_handler)
    app.router.add_post("/api/research", research_handler)
    app.router.add_post("/api/prompt", prompt_handler)
    app.router.add_post("/api/image", image_handler)
    app.router.add_post("/api/kimi_image_describer", kimi_image_describer_handler)
    app.router.add_options("/api/{tail:.*}", lambda _: web.Response(status=204))
    app.router.add_static("/", path=Path(__file__).resolve().parent, show_index=True)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="127.0.0.1", port=8080)
