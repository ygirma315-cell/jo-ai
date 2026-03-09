from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from supabase import Client, create_client

from bot.config import Settings, load_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    api_key: str
    using_service_role: bool
    users_table: str
    history_table: str


def _normalize_table_name(value: str | None, default: str) -> str:
    raw = str(value or "").strip()
    return raw or default


def build_supabase_config(settings: Settings | None = None) -> SupabaseConfig | None:
    active = settings or load_settings()
    url = str(active.supabase_url or "").strip()
    service_role_key = str(active.supabase_service_role_key or "").strip()
    anon_key = str(active.supabase_anon_key or "").strip()
    api_key = service_role_key or anon_key
    if not url or not api_key:
        return None

    return SupabaseConfig(
        url=url,
        api_key=api_key,
        using_service_role=bool(service_role_key),
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
