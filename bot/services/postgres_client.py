from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re

import psycopg
from psycopg import Connection

from bot.config import Settings, load_settings

logger = logging.getLogger(__name__)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str
    users_table: str
    history_table: str


def _safe_table_name(value: str | None, default: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return default
    if _IDENTIFIER_PATTERN.match(candidate):
        return candidate
    logger.warning("Invalid table name '%s'; falling back to '%s'.", candidate, default)
    return default


def build_postgres_config(settings: Settings | None = None) -> PostgresConfig | None:
    active = settings or load_settings()
    dsn = str(active.supabase_db_url or "").strip()
    if not dsn:
        return None
    return PostgresConfig(
        dsn=dsn,
        users_table=_safe_table_name(active.supabase_users_table, "users"),
        history_table=_safe_table_name(active.supabase_history_table, "history"),
    )


@lru_cache(maxsize=1)
def get_postgres_config() -> PostgresConfig | None:
    return build_postgres_config(load_settings())


def open_postgres_connection() -> Connection | None:
    config = get_postgres_config()
    if config is None:
        return None
    try:
        return psycopg.connect(config.dsn, autocommit=False, connect_timeout=5)
    except Exception:
        logger.exception("Failed to connect to Supabase Postgres.")
        return None

