from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

from bot.services.ai_service import DEFAULT_IMAGE_MODEL

DEFAULT_CHAT_MODEL = "meta/llama-3.1-8b-instruct"
DEFAULT_DEEPSEEK_MODEL = "deepseek-ai/deepseek-v3.2"
DEFAULT_KIMI_MODEL = "moonshotai/kimi-k2.5"
DEFAULT_AI_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MINIAPP_URL = "https://ygirma315-cell.github.io/jo-ai/"
@dataclass(frozen=True)
class Settings:
    bot_token: str
    bot_token_env_var: str
    known_users_path: Path
    log_level: str
    ai_api_key: str | None
    ai_base_url: str
    nvidia_api_key: str | None
    nvidia_chat_model: str
    code_model: str
    image_model: str
    deepseek_api_key: str | None
    deepseek_model: str
    kimi_api_key: str | None
    kimi_model: str
    miniapp_url: str | None
    miniapp_api_base: str | None
    public_base_url: str | None
    telegram_webhook_url: str | None
    telegram_webhook_secret: str | None
    allowed_origins: tuple[str, ...]
    request_timeout_seconds: int
    validation_errors: tuple[str, ...]
    validation_warnings: tuple[str, ...]

    def require_valid(self) -> None:
        if self.validation_errors:
            raise RuntimeError("Invalid environment configuration:\n- " + "\n- ".join(self.validation_errors))


def _load_required_bot_token() -> tuple[str, str]:
    for env_name in ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
        value = os.getenv(env_name, "").strip()
        if value:
            return value, env_name
    raise RuntimeError(
        "Missing required Telegram token. Set BOT_TOKEN (or TELEGRAM_BOT_TOKEN) in .env."
    )


def _read_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _normalize_public_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None

    path = parsed.path.rstrip("/")
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return normalized.geturl().rstrip("/")


def _normalize_directory_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None

    path = parsed.path or ""
    if path in {"", "/"}:
        path = ""
    elif not path.endswith("/"):
        last_segment = path.rsplit("/", maxsplit=1)[-1]
        if "." not in last_segment:
            path = f"{path}/"

    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return normalized.geturl() if path else normalized.geturl().rstrip("/")


def _resolve_miniapp_url(raw_value: str | None) -> tuple[str | None, str | None]:
    normalized = _normalize_directory_url(raw_value)
    if not normalized:
        return DEFAULT_MINIAPP_URL, None
    if normalized == DEFAULT_MINIAPP_URL:
        return DEFAULT_MINIAPP_URL, None

    warning = (
        f"MINIAPP_URL must stay pinned to {DEFAULT_MINIAPP_URL}. "
        f"Ignoring {normalized}."
    )
    return DEFAULT_MINIAPP_URL, warning


def _origin_from_url(value: str | None) -> str | None:
    normalized = _normalize_public_url(value)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    return f"{parsed.scheme}://{parsed.netloc}"

def _join_public_url(base_url: str | None, path: str) -> str | None:
    normalized_base = _normalize_public_url(base_url)
    if not normalized_base:
        return None
    joined = f"{normalized_base.rstrip('/')}/{path.lstrip('/')}"
    if path.endswith("/") and not joined.endswith("/"):
        joined = f"{joined}/"
    return joined


def _parse_allowed_origins(
    raw_value: str | None, public_base_url: str | None, miniapp_url: str | None
) -> tuple[str, ...]:
    if raw_value:
        values: list[str] = []
        for item in raw_value.split(","):
            candidate = item.strip()
            if not candidate:
                continue
            if candidate == "*":
                return ("*",)
            origin = _origin_from_url(candidate)
            if origin and origin not in values:
                values.append(origin)
    else:
        values = []

    defaults = values
    public_origin = _origin_from_url(public_base_url)
    if public_origin and public_origin not in defaults:
        defaults.append(public_origin)
    miniapp_origin = _origin_from_url(miniapp_url)
    if miniapp_origin and miniapp_origin not in defaults:
        defaults.append(miniapp_origin)
    return tuple(defaults)


def _parse_timeout_seconds(raw_value: str | None, default: int = 30) -> int:
    try:
        return max(5, int(str(raw_value or default).strip()))
    except ValueError:
        return default


def load_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(dotenv_path=root_dir / ".env")

    bot_token, bot_token_env_var = _load_required_bot_token()

    known_users_raw = os.getenv("KNOWN_USERS_PATH", "bot/data/known_users.json").strip()
    known_users_path = Path(known_users_raw)
    if not known_users_path.is_absolute():
        known_users_path = (root_dir / known_users_path).resolve()

    log_level = _read_env("LOG_LEVEL").upper() or "INFO"

    ai_api_key = _read_env("AI_API_KEY") or _read_env("NVIDIA_API_KEY") or _read_env("JOAI_API_KEY") or _read_env("OPENAI_API_KEY")
    ai_api_key = ai_api_key or None
    ai_base_url = (_read_env("AI_BASE_URL") or DEFAULT_AI_BASE_URL).rstrip("/")

    nvidia_api_key = _read_env("NVIDIA_API_KEY") or _read_env("JOAI_API_KEY") or (ai_api_key or "")
    nvidia_api_key = nvidia_api_key or None
    nvidia_chat_model = _read_env("CHAT_MODEL") or _read_env("NVIDIA_CHAT_MODEL") or DEFAULT_CHAT_MODEL
    code_model = _read_env("CODE_MODEL") or nvidia_chat_model
    image_model = _read_env("IMAGE_MODEL") or DEFAULT_IMAGE_MODEL

    deepseek_api_key = _read_env("DEEPSEEK_API_KEY") or None
    deepseek_model = _read_env("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    kimi_api_key = _read_env("KIMI_API_KEY") or (ai_api_key or "")
    kimi_api_key = kimi_api_key or None
    kimi_model = _read_env("KIMI_MODEL") or DEFAULT_KIMI_MODEL

    public_base_url = (
        _normalize_public_url(_read_env("PUBLIC_BASE_URL"))
        or _normalize_public_url(_read_env("RENDER_EXTERNAL_URL"))
        or _normalize_public_url(_read_env("MINIAPP_API_BASE"))
    )
    miniapp_url, miniapp_url_warning = _resolve_miniapp_url(_read_env("MINIAPP_URL"))
    miniapp_api_base = _normalize_public_url(_read_env("MINIAPP_API_BASE")) or public_base_url
    telegram_webhook_url = _normalize_public_url(_read_env("TELEGRAM_WEBHOOK_URL")) or _join_public_url(
        public_base_url, "/telegram/webhook"
    )
    telegram_webhook_secret = _read_env("TELEGRAM_WEBHOOK_SECRET") or None
    allowed_origins = _parse_allowed_origins(_read_env("ALLOWED_ORIGINS"), public_base_url, miniapp_url)
    request_timeout_seconds = _parse_timeout_seconds(_read_env("REQUEST_TIMEOUT_SECONDS"))

    validation_errors: list[str] = []
    validation_warnings: list[str] = []

    if not ai_api_key:
        validation_errors.append(
            "Missing required AI service credentials. Chat, code, research, prompt, and image endpoints need a server-side key."
        )
    if not public_base_url and not telegram_webhook_url:
        validation_warnings.append(
            "No public base URL detected. Telegram webhook auto-configuration is disabled until a public URL is available."
        )
    if miniapp_url_warning:
        validation_warnings.append(miniapp_url_warning)
    if not miniapp_url:
        validation_errors.append("Mini app URL is missing.")
    if not deepseek_api_key:
        validation_warnings.append("Analysis profile credentials are missing. Analysis profile requests will fail until configured.")
    if not kimi_api_key:
        validation_warnings.append("Vision mode credentials are missing. Vision requests will fail until configured.")

    return Settings(
        bot_token=bot_token,
        bot_token_env_var=bot_token_env_var,
        known_users_path=known_users_path,
        log_level=log_level,
        ai_api_key=ai_api_key,
        ai_base_url=ai_base_url,
        nvidia_api_key=nvidia_api_key,
        nvidia_chat_model=nvidia_chat_model,
        code_model=code_model,
        image_model=image_model,
        deepseek_api_key=deepseek_api_key,
        deepseek_model=deepseek_model,
        kimi_api_key=kimi_api_key,
        kimi_model=kimi_model,
        miniapp_url=miniapp_url,
        miniapp_api_base=miniapp_api_base,
        public_base_url=public_base_url,
        telegram_webhook_url=telegram_webhook_url,
        telegram_webhook_secret=telegram_webhook_secret,
        allowed_origins=allowed_origins,
        request_timeout_seconds=request_timeout_seconds,
        validation_errors=tuple(validation_errors),
        validation_warnings=tuple(validation_warnings),
    )
