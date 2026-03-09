from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Literal

from psycopg import sql
from supabase import Client, create_client

from bot.config import Settings, load_settings
from bot.services.postgres_client import PostgresConfig, build_postgres_config, open_postgres_connection
from bot.services.supabase_client import SupabaseConfig, build_supabase_config

logger = logging.getLogger(__name__)
TrackingBackend = Literal["postgres", "supabase_http", "disabled"]


@dataclass(slots=True)
class TrackingIdentity:
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


def _clean_text(value: str | None, max_len: int) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:max_len]


def _clean_history_text(value: str | None, max_len: int = 12000) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:max_len]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(0, int(default))
    return max(0, parsed)


def _response_rowcount(response: Any) -> int:
    count = getattr(response, "count", None)
    if isinstance(count, int):
        return max(0, count)
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return 1 if data else 0
    return 0


class SupabaseTrackingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()
        self._postgres_config: PostgresConfig | None = build_postgres_config(self._settings)
        self._supabase_config: SupabaseConfig | None = build_supabase_config(self._settings)
        self._supabase_client: Client | None = None
        self._backend: TrackingBackend = "disabled"

        if self._postgres_config is not None:
            self._backend = "postgres"
            logger.info(
                "Tracking initialized | backend=postgres users_table=%s history_table=%s",
                self._postgres_config.users_table,
                self._postgres_config.history_table,
            )
            return

        if self._supabase_config is None:
            logger.warning(
                "Tracking disabled: SUPABASE_DB_URL is unavailable and SUPABASE_URL/key are not configured."
            )
            return

        try:
            self._supabase_client = create_client(self._supabase_config.url, self._supabase_config.api_key)
            self._backend = "supabase_http"
            logger.info(
                "Tracking initialized | backend=supabase_http users_table=%s history_table=%s using_service_role=%s",
                self._supabase_config.users_table,
                self._supabase_config.history_table,
                self._supabase_config.using_service_role,
            )
        except Exception:
            logger.exception("Tracking disabled: failed to initialize Supabase HTTP client.")

    @property
    def enabled(self) -> bool:
        return self._backend != "disabled"

    @property
    def backend(self) -> TrackingBackend:
        return self._backend

    async def verify_connection(self) -> bool:
        if not self.enabled:
            logger.warning("Supabase tracking startup test skipped: tracking is disabled.")
            return False

        logger.info("Supabase tracking startup test begin | backend=%s", self._backend)
        try:
            if self._backend == "postgres":
                await asyncio.to_thread(self._verify_postgres_connection_sync)
            elif self._backend == "supabase_http":
                await asyncio.to_thread(self._verify_supabase_connection_sync)
            else:
                return False
            logger.info("Supabase tracking startup test success | backend=%s", self._backend)
            return True
        except Exception:
            logger.exception("Supabase tracking startup test failed | backend=%s", self._backend)
            return False

    async def track_action(
        self,
        *,
        identity: TrackingIdentity | None,
        message_type: str,
        user_message: str,
        bot_reply: str | None,
        model_used: str | None,
        success: bool,
        message_increment: int = 0,
        image_increment: int = 0,
    ) -> None:
        if not self.enabled:
            logger.warning("Tracking skipped: service is disabled.")
            return
        if identity is None or identity.telegram_id <= 0:
            logger.warning("Tracking skipped: missing telegram identity.")
            return

        safe_message_increment = max(0, int(message_increment))
        safe_image_increment = max(0, int(image_increment))

        logger.info(
            "Tracking start | backend=%s telegram_id=%s message_type=%s success=%s message_inc=%s image_inc=%s",
            self._backend,
            identity.telegram_id,
            message_type,
            bool(success),
            safe_message_increment,
            safe_image_increment,
        )

        try:
            if self._backend == "postgres":
                users_upserted, history_inserted = await asyncio.to_thread(
                    self._track_action_postgres_sync,
                    identity,
                    message_type,
                    user_message,
                    bot_reply,
                    model_used,
                    success,
                    safe_message_increment,
                    safe_image_increment,
                )
            elif self._backend == "supabase_http":
                users_upserted, history_inserted = await asyncio.to_thread(
                    self._track_action_supabase_sync,
                    identity,
                    message_type,
                    user_message,
                    bot_reply,
                    model_used,
                    success,
                    safe_message_increment,
                    safe_image_increment,
                )
            else:
                logger.warning("Tracking skipped: no active tracking backend.")
                return
        except Exception:
            logger.exception(
                "Supabase tracking failed | backend=%s telegram_id=%s message_type=%s",
                self._backend,
                identity.telegram_id,
                message_type,
            )
            raise

        logger.info(
            "Tracking success | backend=%s telegram_id=%s message_type=%s users_upserted=%s history_inserted=%s",
            self._backend,
            identity.telegram_id,
            message_type,
            users_upserted,
            history_inserted,
        )

    def _verify_postgres_connection_sync(self) -> None:
        connection = open_postgres_connection()
        if connection is None:
            raise RuntimeError("Supabase Postgres connection is unavailable.")
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("select 1")
                    cursor.fetchone()
        finally:
            with suppress(Exception):
                connection.close()

    def _verify_supabase_connection_sync(self) -> None:
        if self._supabase_client is None or self._supabase_config is None:
            raise RuntimeError("Supabase HTTP client is not initialized.")
        self._supabase_client.table(self._supabase_config.users_table).select(
            "telegram_id",
            count="exact",
        ).limit(1).execute()

    def _track_action_postgres_sync(
        self,
        identity: TrackingIdentity,
        message_type: str,
        user_message: str,
        bot_reply: str | None,
        model_used: str | None,
        success: bool,
        message_increment: int,
        image_increment: int,
    ) -> tuple[int, int]:
        if not self.enabled or self._backend != "postgres":
            raise RuntimeError("Postgres tracking backend is unavailable.")
        assert self._postgres_config is not None

        connection = open_postgres_connection()
        if connection is None:
            logger.error(
                "Tracking failed: Postgres connection unavailable | telegram_id=%s message_type=%s",
                identity.telegram_id,
                message_type,
            )
            raise RuntimeError("Postgres connection is unavailable.")

        users_upserted = 0
        history_inserted = 0
        try:
            users_identifier = sql.Identifier(self._postgres_config.users_table)
            history_identifier = sql.Identifier(self._postgres_config.history_table)

            with connection:
                with connection.cursor() as cursor:
                    logger.info(
                        "Tracking user upsert start | backend=postgres telegram_id=%s",
                        identity.telegram_id,
                    )
                    cursor.execute(
                        sql.SQL(
                            """
                            insert into {users} as u (
                                telegram_id,
                                username,
                                first_name,
                                last_name,
                                last_seen_at,
                                total_messages,
                                total_images
                            ) values (
                                %s, %s, %s, %s, timezone('utc', now()), %s, %s
                            )
                            on conflict (telegram_id) do update set
                                username = excluded.username,
                                first_name = excluded.first_name,
                                last_name = excluded.last_name,
                                last_seen_at = timezone('utc', now()),
                                total_messages = coalesce(u.total_messages, 0) + excluded.total_messages,
                                total_images = coalesce(u.total_images, 0) + excluded.total_images
                            """
                        ).format(users=users_identifier),
                        (
                            identity.telegram_id,
                            _clean_text(identity.username, max_len=128),
                            _clean_text(identity.first_name, max_len=128),
                            _clean_text(identity.last_name, max_len=128),
                            message_increment,
                            image_increment,
                        ),
                    )
                    users_upserted = max(0, int(cursor.rowcount or 0))
                    logger.info(
                        "Tracking user upsert success | backend=postgres telegram_id=%s rows=%s",
                        identity.telegram_id,
                        users_upserted,
                    )

                    logger.info(
                        "Tracking history insert start | backend=postgres telegram_id=%s message_type=%s",
                        identity.telegram_id,
                        message_type,
                    )
                    cursor.execute(
                        sql.SQL(
                            """
                            insert into {history} (
                                telegram_id,
                                message_type,
                                user_message,
                                bot_reply,
                                model_used,
                                success,
                                created_at
                            ) values (
                                %s, %s, %s, %s, %s, %s, timezone('utc', now())
                            )
                            """
                        ).format(history=history_identifier),
                        (
                            identity.telegram_id,
                            _clean_text(message_type, max_len=64) or "unknown",
                            _clean_history_text(user_message, max_len=16000),
                            _clean_history_text(bot_reply, max_len=16000),
                            _clean_text(model_used, max_len=256),
                            bool(success),
                        ),
                    )
                    history_inserted = max(0, int(cursor.rowcount or 0))
                    logger.info(
                        "Tracking history insert success | backend=postgres telegram_id=%s rows=%s",
                        identity.telegram_id,
                        history_inserted,
                    )
            return users_upserted, history_inserted
        except Exception:
            logger.exception(
                "Postgres tracking failed | telegram_id=%s message_type=%s",
                identity.telegram_id,
                message_type,
            )
            raise
        finally:
            with suppress(Exception):
                connection.close()

    def _track_action_supabase_sync(
        self,
        identity: TrackingIdentity,
        message_type: str,
        user_message: str,
        bot_reply: str | None,
        model_used: str | None,
        success: bool,
        message_increment: int,
        image_increment: int,
    ) -> tuple[int, int]:
        if not self.enabled or self._backend != "supabase_http":
            raise RuntimeError("Supabase HTTP tracking backend is unavailable.")
        if self._supabase_client is None or self._supabase_config is None:
            raise RuntimeError("Supabase HTTP client is not initialized.")

        existing_user = self._fetch_existing_user_row(identity.telegram_id)
        current_messages = _safe_non_negative_int(existing_user.get("total_messages") if existing_user else 0)
        current_images = _safe_non_negative_int(existing_user.get("total_images") if existing_user else 0)

        username = _clean_text(identity.username, max_len=128) or _clean_text(
            existing_user.get("username") if existing_user else None,
            max_len=128,
        )
        first_name = _clean_text(identity.first_name, max_len=128) or _clean_text(
            existing_user.get("first_name") if existing_user else None,
            max_len=128,
        )
        last_name = _clean_text(identity.last_name, max_len=128) or _clean_text(
            existing_user.get("last_name") if existing_user else None,
            max_len=128,
        )

        user_payload = {
            "telegram_id": identity.telegram_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "last_seen_at": _utc_now_iso(),
            "total_messages": current_messages + message_increment,
            "total_images": current_images + image_increment,
        }
        logger.info(
            "Tracking user upsert start | backend=supabase_http telegram_id=%s",
            identity.telegram_id,
        )
        user_response = self._supabase_client.table(self._supabase_config.users_table).upsert(
            user_payload,
            on_conflict="telegram_id",
            returning="representation",
            count="exact",
        ).execute()
        users_upserted = _response_rowcount(user_response)
        if users_upserted <= 0:
            raise RuntimeError("Supabase user upsert returned zero rows.")
        logger.info(
            "Tracking user upsert success | backend=supabase_http telegram_id=%s rows=%s",
            identity.telegram_id,
            users_upserted,
        )

        history_payload = {
            "telegram_id": identity.telegram_id,
            "message_type": _clean_text(message_type, max_len=64) or "unknown",
            "user_message": _clean_history_text(user_message, max_len=16000),
            "bot_reply": _clean_history_text(bot_reply, max_len=16000),
            "model_used": _clean_text(model_used, max_len=256),
            "success": bool(success),
            "created_at": _utc_now_iso(),
        }
        logger.info(
            "Tracking history insert start | backend=supabase_http telegram_id=%s message_type=%s",
            identity.telegram_id,
            message_type,
        )
        history_response = self._supabase_client.table(self._supabase_config.history_table).insert(
            history_payload,
            returning="representation",
            count="exact",
        ).execute()
        history_inserted = _response_rowcount(history_response)
        if history_inserted <= 0:
            raise RuntimeError("Supabase history insert returned zero rows.")
        logger.info(
            "Tracking history insert success | backend=supabase_http telegram_id=%s rows=%s",
            identity.telegram_id,
            history_inserted,
        )
        return users_upserted, history_inserted

    def _fetch_existing_user_row(self, telegram_id: int) -> dict[str, Any] | None:
        if self._supabase_client is None or self._supabase_config is None:
            return None
        response = self._supabase_client.table(self._supabase_config.users_table).select(
            "username,first_name,last_name,total_messages,total_images",
            count="exact",
        ).eq("telegram_id", telegram_id).limit(1).execute()
        data = getattr(response, "data", None)
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first
        return None
