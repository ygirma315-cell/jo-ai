from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re
from typing import Literal

from supabase import Client, create_client

from bot.config import Settings, load_settings

logger = logging.getLogger(__name__)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    api_key: str
    key_type: Literal["service_role", "anon"]
    using_service_role: bool
    users_table: str
    history_table: str


def _normalize_table_name(value: str | None, default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default

    candidate = raw.strip().strip('"')
    if "." in candidate:
        schema, table = candidate.split(".", maxsplit=1)
        candidate = table.strip().strip('"')
        logger.warning(
            "Supabase table value '%s' includes schema '%s'; using table name '%s'.",
            raw,
            schema.strip().strip('"'),
            candidate,
        )
    if not _IDENTIFIER_PATTERN.match(candidate):
        logger.warning("Invalid Supabase table name '%s'; falling back to '%s'.", raw, default)
        return default
    return candidate


def build_supabase_config(settings: Settings | None = None) -> SupabaseConfig | None:
    active = settings or load_settings()
    url = str(active.supabase_url or "").strip()
    service_role_key = str(active.supabase_service_role_key or "").strip()
    anon_key = str(active.supabase_anon_key or "").strip()
    if not url:
        return None

    key_type: Literal["service_role", "anon"] | None = None
    api_key = ""
    if service_role_key:
        key_type = "service_role"
        api_key = service_role_key
    elif anon_key and active.supabase_allow_anon_fallback:
        key_type = "anon"
        api_key = anon_key
    elif anon_key and not active.supabase_allow_anon_fallback:
        logger.warning(
            "Supabase HTTP write config skipped: SUPABASE_ANON_KEY is present but SUPABASE_ALLOW_ANON_FALLBACK is disabled. Set SUPABASE_SERVICE_ROLE_KEY."
        )
        return None

    if not key_type or not api_key:
        return None

    return SupabaseConfig(
        url=url,
        api_key=api_key,
        key_type=key_type,
        using_service_role=(key_type == "service_role"),
        users_table=_normalize_table_name(active.supabase_users_table, "users"),
        history_table=_normalize_table_name(active.supabase_history_table, "history"),
    )


@lru_cache(maxsize=1)
def get_supabase_config() -> SupabaseConfig | None:
    return build_supabase_config(load_settings())


@lru_cache(maxsize=1)
def get_supabase_client() -> Client | None:
    config = get_supabase_config()
    if config is None:
        return None

    try:
        return create_client(config.url, config.api_key)
    except Exception:
        logger.exception("Failed to initialize Supabase client.")
        return None
