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
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_TTS_FUNCTION_ID = "bc45d9e9-7c78-4d56-9737-e27011962ba8"
DEFAULT_AI_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_POLLINATIONS_BASE_URL = "https://gen.pollinations.ai"
DEFAULT_POLLINATIONS_IMAGE_MODEL_CHAT_GBT = "gpt-image-1-mini"
DEFAULT_POLLINATIONS_IMAGE_MODEL_GROK_IMAGINE = "grok-imagine"
DEFAULT_POLLINATIONS_VIDEO_MODEL_GROK_TEXT_TO_VIDEO = "grok-video"
DEFAULT_MINIAPP_URL = "https://ygirma315-cell.github.io/jo-ai/"
DEFAULT_ENGAGEMENT_MESSAGE_TEMPLATE = "What do you want to do with your chat bot today?"
DEFAULT_HEARTBEAT_TELEGRAM_ID = 7799059248
_PLACEHOLDER_VALUE_SNIPPETS = (
    "[your-password]",
    "<your-password>",
    "your-password",
    "your_password",
    "yourpassword",
    "replace-me",
    "replace_me",
    "changeme",
    "example",
)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    bot_token_env_var: str
    known_users_path: Path
    log_level: str
    ai_api_key: str | None
    ai_base_url: str
    nvidia_api_key: str | None
    image_api_key: str | None
    nvidia_chat_model: str
    code_model: str
    image_model: str
    pollinations_api_key: str | None
    pollinations_base_url: str
    pollinations_image_model_chat_gbt: str
    pollinations_image_model_grok_imagine: str
    pollinations_video_model_grok_text_to_video: str
    deepseek_api_key: str | None
    deepseek_model: str
    kimi_api_key: str | None
    kimi_model: str
    gemini_api_key: str | None
    gemini_model: str
    gemini_fallback_models: tuple[str, ...]
    tts_api_key: str | None
    tts_function_id: str
    supabase_url: str | None
    supabase_anon_key: str | None
    supabase_service_role_key: str | None
    supabase_allow_anon_fallback: bool
    supabase_db_url: str | None
    supabase_users_table: str
    supabase_history_table: str
    miniapp_url: str | None
    miniapp_api_base: str | None
    public_base_url: str | None
    telegram_webhook_url: str | None
    telegram_webhook_secret: str | None
    admin_dashboard_owner_telegram_id: int | None
    admin_dashboard_allowlist_telegram_ids: tuple[int, ...]
    admin_dashboard_telegram_bot_token: str | None
    admin_signin_token: str | None
    engagement_enabled: bool
    engagement_message_template: str
    engagement_inactivity_minutes: int
    engagement_cooldown_minutes: int
    engagement_batch_size: int
    keepalive_self_ping_enabled: bool
    keepalive_ping_interval_minutes: int
    keepalive_heartbeat_enabled: bool
    keepalive_heartbeat_interval_minutes: int
    keepalive_heartbeat_telegram_id: int | None
    keepalive_heartbeat_message: str
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


def _read_alias_env(*names: str) -> tuple[str | None, str | None]:
    for name in names:
        value = _read_env(name)
        if value:
            return value, name
    return None, None


def _alias_conflict_warning(*names: str) -> str | None:
    seen: dict[str, str] = {}
    for name in names:
        value = _read_env(name)
        if value:
            seen[name] = value
    if len(seen) <= 1:
        return None

    unique_values = {value for value in seen.values()}
    if len(unique_values) <= 1:
        return None

    ordered_names = ", ".join(seen.keys())
    return f"Conflicting Supabase env aliases set with different values: {ordered_names}."


def _looks_like_placeholder(value: str | None) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in _PLACEHOLDER_VALUE_SNIPPETS)


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


def _parse_positive_int(raw_value: str | None) -> int | None:
    try:
        parsed = int(str(raw_value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _parse_bool_env(raw_value: str | None, default: bool = False) -> bool:
    raw = str(raw_value or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_csv_positive_ints(raw_value: str | None) -> tuple[int, ...]:
    values: list[int] = []
    for token in str(raw_value or "").split(","):
        parsed = _parse_positive_int(token)
        if parsed is not None and parsed not in values:
            values.append(parsed)
    return tuple(values)


def _parse_bounded_int(raw_value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_csv_models(raw_value: str | None) -> tuple[str, ...]:
    values: list[str] = []
    for token in str(raw_value or "").split(","):
        candidate = token.strip()
        if not candidate:
            continue
        if candidate not in values:
            values.append(candidate)
    return tuple(values)


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
    image_api_key = _read_env("IMAGE_API_KEY") or nvidia_api_key or ai_api_key
    image_api_key = image_api_key or None
    nvidia_chat_model = _read_env("CHAT_MODEL") or _read_env("NVIDIA_CHAT_MODEL") or DEFAULT_CHAT_MODEL
    code_model = _read_env("CODE_MODEL") or nvidia_chat_model
    image_model = _read_env("IMAGE_MODEL") or DEFAULT_IMAGE_MODEL
    pollinations_api_key = _read_env("POLLINATIONS_API_KEY") or None
    pollinations_base_url = (_read_env("POLLINATIONS_BASE_URL") or DEFAULT_POLLINATIONS_BASE_URL).rstrip("/")
    pollinations_image_model_chat_gbt = (
        _read_env("POLLINATIONS_IMAGE_MODEL_CHAT_GBT") or DEFAULT_POLLINATIONS_IMAGE_MODEL_CHAT_GBT
    )
    pollinations_image_model_grok_imagine = (
        _read_env("POLLINATIONS_IMAGE_MODEL_GROK_IMAGINE") or DEFAULT_POLLINATIONS_IMAGE_MODEL_GROK_IMAGINE
    )
    pollinations_video_model_grok_text_to_video = (
        _read_env("POLLINATIONS_VIDEO_MODEL_GROK_TEXT_TO_VIDEO") or DEFAULT_POLLINATIONS_VIDEO_MODEL_GROK_TEXT_TO_VIDEO
    )

    deepseek_api_key = _read_env("DEEPSEEK_API_KEY") or None
    deepseek_model = _read_env("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    kimi_api_key = _read_env("KIMI_API_KEY") or (ai_api_key or "")
    kimi_api_key = kimi_api_key or None
    kimi_model = _read_env("KIMI_MODEL") or DEFAULT_KIMI_MODEL
    gemini_api_key = (
        _read_env("GEMINI_API_KEY")
        or _read_env("GOOGLE_AI_STUDIO_API_KEY")
        or _read_env("GOOGLE_API_KEY")
        or ""
    )
    gemini_api_key = gemini_api_key or None
    gemini_model = _read_env("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    gemini_fallback_models = _parse_csv_models(_read_env("GEMINI_FALLBACK_MODELS"))
    tts_api_key = _read_env("TTS_API_KEY") or _read_env("NVIDIA_TTS_API_KEY") or nvidia_api_key or ai_api_key
    tts_api_key = tts_api_key or None
    tts_function_id = _read_env("TTS_FUNCTION_ID") or DEFAULT_TTS_FUNCTION_ID
    supabase_url_raw, _supabase_url_source = _read_alias_env("SUPABASE_URL", "SUPABASE_PROJECT_URL")
    supabase_anon_key_raw, _supabase_anon_source = _read_alias_env("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY")
    supabase_service_role_key_raw, _supabase_service_role_source = _read_alias_env(
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SECRET_KEY",
    )
    supabase_db_url_raw, _supabase_db_url_source = _read_alias_env(
        "SUPABASE_DB_URL",
        "SUPABASE_DIRECT_CONNECTION_STRING",
    )
    supabase_url = _normalize_public_url(supabase_url_raw) or None
    supabase_anon_key = supabase_anon_key_raw or None
    supabase_service_role_key = supabase_service_role_key_raw or None
    supabase_allow_anon_fallback = _parse_bool_env(_read_env("SUPABASE_ALLOW_ANON_FALLBACK"), default=False)
    supabase_db_url = supabase_db_url_raw or None
    supabase_users_table = _read_env("SUPABASE_USERS_TABLE") or "users"
    supabase_history_table = _read_env("SUPABASE_HISTORY_TABLE") or "history"

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
    admin_dashboard_owner_telegram_id = _parse_positive_int(_read_env("ADMIN_DASHBOARD_OWNER_TELEGRAM_ID"))
    admin_dashboard_allowlist_telegram_ids = _parse_csv_positive_ints(
        _read_env("ADMIN_DASHBOARD_ALLOWLIST_TELEGRAM_IDS")
        or _read_env("ADMIN_ALLOWLIST_TELEGRAM_IDS")
    )
    if admin_dashboard_owner_telegram_id and admin_dashboard_owner_telegram_id not in admin_dashboard_allowlist_telegram_ids:
        admin_dashboard_allowlist_telegram_ids = (
            admin_dashboard_owner_telegram_id,
            *admin_dashboard_allowlist_telegram_ids,
        )
    admin_dashboard_telegram_bot_token = _read_env("ADMIN_DASHBOARD_TELEGRAM_BOT_TOKEN") or None
    admin_signin_token = _read_env("ADMIN_SIGNIN_TOKEN") or _read_env("ADMIN_DASHBOARD_TOKEN") or None
    engagement_enabled = _parse_bool_env(_read_env("ENGAGEMENT_ENABLED"), default=True)
    engagement_message_template = (
        _read_env("ENGAGEMENT_MESSAGE_TEMPLATE") or DEFAULT_ENGAGEMENT_MESSAGE_TEMPLATE
    )[:400]
    if not engagement_message_template.strip():
        engagement_message_template = DEFAULT_ENGAGEMENT_MESSAGE_TEMPLATE
    engagement_inactivity_minutes = _parse_bounded_int(
        _read_env("ENGAGEMENT_INACTIVITY_MINUTES"),
        default=240,
        minimum=30,
        maximum=10_080,
    )
    engagement_cooldown_minutes = _parse_bounded_int(
        _read_env("ENGAGEMENT_COOLDOWN_MINUTES"),
        default=720,
        minimum=30,
        maximum=43_200,
    )
    engagement_batch_size = _parse_bounded_int(
        _read_env("ENGAGEMENT_BATCH_SIZE"),
        default=30,
        minimum=1,
        maximum=500,
    )
    keepalive_self_ping_enabled = _parse_bool_env(_read_env("KEEPALIVE_SELF_PING_ENABLED"), default=True)
    keepalive_ping_interval_minutes = _parse_bounded_int(
        _read_env("KEEPALIVE_PING_INTERVAL_MINUTES"),
        default=5,
        minimum=1,
        maximum=120,
    )
    keepalive_heartbeat_enabled = _parse_bool_env(_read_env("KEEPALIVE_HEARTBEAT_ENABLED"), default=False)
    keepalive_heartbeat_interval_minutes = _parse_bounded_int(
        _read_env("KEEPALIVE_HEARTBEAT_INTERVAL_MINUTES"),
        default=10,
        minimum=1,
        maximum=180,
    )
    keepalive_heartbeat_telegram_id = _parse_positive_int(
        _read_env("KEEPALIVE_HEARTBEAT_TELEGRAM_ID")
        or _read_env("ADMIN_DASHBOARD_OWNER_TELEGRAM_ID")
        or str(DEFAULT_HEARTBEAT_TELEGRAM_ID)
    )
    keepalive_heartbeat_message = (
        _read_env("KEEPALIVE_HEARTBEAT_MESSAGE") or "I'm making your bot active automatically."
    )[:500]
    if not keepalive_heartbeat_message.strip():
        keepalive_heartbeat_message = "I'm making your bot active automatically."
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
    if not admin_dashboard_owner_telegram_id:
        validation_warnings.append(
            "ADMIN_DASHBOARD_OWNER_TELEGRAM_ID is missing. Telegram-ID admin login shortcut is disabled."
        )
    if not admin_dashboard_allowlist_telegram_ids:
        validation_warnings.append(
            "ADMIN_DASHBOARD_ALLOWLIST_TELEGRAM_IDS is empty. Telegram admin login is disabled until at least one Telegram ID is allowed."
        )
    if keepalive_heartbeat_enabled and not keepalive_heartbeat_telegram_id:
        validation_warnings.append(
            "KEEPALIVE_HEARTBEAT_ENABLED is true but KEEPALIVE_HEARTBEAT_TELEGRAM_ID is missing."
        )
    if miniapp_url_warning:
        validation_warnings.append(miniapp_url_warning)
    if not miniapp_url:
        validation_errors.append("Mini app URL is missing.")
    if not deepseek_api_key:
        validation_warnings.append("DeepSeek credentials are missing. DeepSeek mode will use default credentials.")
    if not kimi_api_key:
        validation_warnings.append("Vision mode credentials are missing. Vision requests will fail until configured.")
    if not gemini_api_key:
        validation_warnings.append("Gemini credentials are missing. Gemini mode will be unavailable until GEMINI_API_KEY is configured.")
    if not tts_api_key:
        validation_warnings.append("Text-to-Speech credentials are missing. TTS will use fallback synthesis.")
    if not pollinations_api_key:
        validation_warnings.append(
            "Pollinations credentials are missing. Chat GBT, Grok Imagine, and Grok Text to Video modes will be unavailable."
        )
    for alias_warning in (
        _alias_conflict_warning("SUPABASE_URL", "SUPABASE_PROJECT_URL"),
        _alias_conflict_warning("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY"),
        _alias_conflict_warning("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"),
        _alias_conflict_warning("SUPABASE_DB_URL", "SUPABASE_DIRECT_CONNECTION_STRING"),
    ):
        if alias_warning:
            validation_warnings.append(alias_warning)
    if supabase_url_raw and not supabase_url:
        validation_warnings.append(
            "SUPABASE_URL is set but is not a valid URL. Supabase HTTP tracking is disabled until this is fixed."
        )
    if _looks_like_placeholder(supabase_db_url):
        validation_warnings.append(
            "SUPABASE_DB_URL looks like a placeholder value. Direct Postgres tracking will be disabled."
        )
    if str(supabase_service_role_key or "").strip().lower().startswith("sb_publishable_"):
        validation_warnings.append(
            "SUPABASE_SERVICE_ROLE_KEY appears to be a publishable/anon key. Use the secret service role key."
        )
    if supabase_allow_anon_fallback:
        validation_warnings.append(
            "SUPABASE_ALLOW_ANON_FALLBACK is enabled. Server-side writes may use SUPABASE_ANON_KEY if service role is absent."
        )
    if supabase_url and not (supabase_service_role_key or supabase_anon_key):
        validation_warnings.append(
            "SUPABASE_URL is set but no key is configured. Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY."
        )
    if (supabase_service_role_key or supabase_anon_key) and not supabase_url:
        validation_warnings.append(
            "A Supabase key is set but SUPABASE_URL is missing. Supabase HTTP client is disabled."
        )
    if supabase_url and supabase_anon_key and not supabase_service_role_key:
        if supabase_allow_anon_fallback:
            validation_warnings.append(
                "Tracking may use SUPABASE_ANON_KEY fallback. If RLS blocks inserts, set SUPABASE_SERVICE_ROLE_KEY."
            )
        else:
            validation_warnings.append(
                "SUPABASE_ANON_KEY is set but anon fallback is disabled for server writes. Set SUPABASE_SERVICE_ROLE_KEY."
            )
    if (
        supabase_url
        and supabase_anon_key
        and not supabase_service_role_key
        and not supabase_allow_anon_fallback
        and not supabase_db_url
    ):
        validation_warnings.append(
            "No service-role Supabase write key is available and anon fallback is disabled. Set SUPABASE_SERVICE_ROLE_KEY."
        )
    if (supabase_url or supabase_anon_key or supabase_service_role_key) and not supabase_db_url:
        validation_warnings.append(
            "SUPABASE_DB_URL is missing. Direct Postgres tracking is disabled; Supabase HTTP tracking can still run."
        )

    return Settings(
        bot_token=bot_token,
        bot_token_env_var=bot_token_env_var,
        known_users_path=known_users_path,
        log_level=log_level,
        ai_api_key=ai_api_key,
        ai_base_url=ai_base_url,
        nvidia_api_key=nvidia_api_key,
        image_api_key=image_api_key,
        nvidia_chat_model=nvidia_chat_model,
        code_model=code_model,
        image_model=image_model,
        pollinations_api_key=pollinations_api_key,
        pollinations_base_url=pollinations_base_url,
        pollinations_image_model_chat_gbt=pollinations_image_model_chat_gbt,
        pollinations_image_model_grok_imagine=pollinations_image_model_grok_imagine,
        pollinations_video_model_grok_text_to_video=pollinations_video_model_grok_text_to_video,
        deepseek_api_key=deepseek_api_key,
        deepseek_model=deepseek_model,
        kimi_api_key=kimi_api_key,
        kimi_model=kimi_model,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_fallback_models=gemini_fallback_models,
        tts_api_key=tts_api_key,
        tts_function_id=tts_function_id,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
        supabase_service_role_key=supabase_service_role_key,
        supabase_allow_anon_fallback=supabase_allow_anon_fallback,
        supabase_db_url=supabase_db_url,
        supabase_users_table=supabase_users_table,
        supabase_history_table=supabase_history_table,
        miniapp_url=miniapp_url,
        miniapp_api_base=miniapp_api_base,
        public_base_url=public_base_url,
        telegram_webhook_url=telegram_webhook_url,
        telegram_webhook_secret=telegram_webhook_secret,
        admin_dashboard_owner_telegram_id=admin_dashboard_owner_telegram_id,
        admin_dashboard_allowlist_telegram_ids=admin_dashboard_allowlist_telegram_ids,
        admin_dashboard_telegram_bot_token=admin_dashboard_telegram_bot_token,
        admin_signin_token=admin_signin_token,
        engagement_enabled=engagement_enabled,
        engagement_message_template=engagement_message_template,
        engagement_inactivity_minutes=engagement_inactivity_minutes,
        engagement_cooldown_minutes=engagement_cooldown_minutes,
        engagement_batch_size=engagement_batch_size,
        keepalive_self_ping_enabled=keepalive_self_ping_enabled,
        keepalive_ping_interval_minutes=keepalive_ping_interval_minutes,
        keepalive_heartbeat_enabled=keepalive_heartbeat_enabled,
        keepalive_heartbeat_interval_minutes=keepalive_heartbeat_interval_minutes,
        keepalive_heartbeat_telegram_id=keepalive_heartbeat_telegram_id,
        keepalive_heartbeat_message=keepalive_heartbeat_message,
        allowed_origins=allowed_origins,
        request_timeout_seconds=request_timeout_seconds,
        validation_errors=tuple(validation_errors),
        validation_warnings=tuple(validation_warnings),
    )
