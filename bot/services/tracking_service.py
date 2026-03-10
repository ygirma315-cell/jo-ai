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
        self._disabled_reason: str | None = None

        if self._supabase_config is not None:
            try:
                self._supabase_client = create_client(self._supabase_config.url, self._supabase_config.api_key)
            except Exception:
                logger.exception("SUPABASE CONFIG INVALID | failed to initialize Supabase HTTP client.")

        if self._postgres_config is not None:
            self._backend = "postgres"
            self._disabled_reason = None
            logger.info(
                "SUPABASE CONFIG LOADED | backend=postgres users_table=%s history_table=%s has_http_fallback=%s http_key_type=%s",
                self._postgres_config.users_table,
                self._postgres_config.history_table,
                bool(self._supabase_client and self._supabase_config),
                self._supabase_config.key_type if self._supabase_config else "none",
            )
            return

        if self._supabase_client is not None and self._supabase_config is not None:
            self._backend = "supabase_http"
            self._disabled_reason = None
            logger.info(
                "SUPABASE CONFIG LOADED | backend=supabase_http users_table=%s history_table=%s key_type=%s using_service_role=%s",
                self._supabase_config.users_table,
                self._supabase_config.history_table,
                self._supabase_config.key_type,
                self._supabase_config.using_service_role,
            )
            return

        reasons: list[str] = []
        if self._settings.supabase_db_url and self._postgres_config is None:
            reasons.append("SUPABASE_DB_URL is set but invalid/unusable")
        if self._settings.supabase_url and not (self._settings.supabase_service_role_key or self._settings.supabase_anon_key):
            reasons.append("SUPABASE_URL is set without key")
        if (
            self._settings.supabase_url
            and self._settings.supabase_anon_key
            and not self._settings.supabase_service_role_key
            and not self._settings.supabase_allow_anon_fallback
        ):
            reasons.append("SUPABASE_ANON_KEY present but anon fallback disabled; set SUPABASE_SERVICE_ROLE_KEY")
        if self._supabase_config is not None and self._supabase_client is None:
            reasons.append("Supabase HTTP client init failed")
        if not reasons:
            reasons.append("No tracking env vars configured")
        self._disabled_reason = "; ".join(reasons)
        logger.warning("SUPABASE CONFIG INVALID | reason=%s", self._disabled_reason)

    @property
    def enabled(self) -> bool:
        return self._backend != "disabled"

    @property
    def backend(self) -> TrackingBackend:
        return self._backend

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    async def verify_connection(self) -> bool:
        if not self.enabled:
            logger.warning("SUPABASE CONFIG INVALID | reason=%s", self._disabled_reason or "tracking disabled")
            return False

        logger.info("SUPABASE CONNECTION VERIFY START | backend=%s", self._backend)
        try:
            if self._backend == "postgres":
                await asyncio.to_thread(self._verify_postgres_connection_sync)
            elif self._backend == "supabase_http":
                await asyncio.to_thread(self._verify_supabase_connection_sync)
            else:
                return False
            logger.info("SUPABASE CONNECTION VERIFY SUCCESS | backend=%s", self._backend)
            return True
        except Exception as exc:
            logger.exception(
                "SUPABASE CONNECTION VERIFY FAILED | backend=%s error=%s",
                self._backend,
                exc,
            )
            if self._backend == "postgres" and self._switch_to_http_backend(str(exc)):
                try:
                    await asyncio.to_thread(self._verify_supabase_connection_sync)
                    logger.info("SUPABASE CONNECTION VERIFY SUCCESS | backend=%s", self._backend)
                    return True
                except Exception as fallback_exc:
                    logger.exception(
                        "SUPABASE CONNECTION VERIFY FAILED | backend=%s error=%s",
                        self._backend,
                        fallback_exc,
                    )
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
    ) -> tuple[int, int]:
        if not self.enabled:
            logger.warning("TRACKING FAILED user=unknown error=tracking backend disabled reason=%s", self._disabled_reason)
            return 0, 0
        if identity is None or identity.telegram_id <= 0:
            logger.warning("TRACKING FAILED user=unknown error=missing telegram identity")
            return 0, 0

        safe_message_increment = max(0, int(message_increment))
        safe_image_increment = max(0, int(image_increment))

        logger.info(
            "TRACKING START user=%s message_type=%s backend=%s success=%s message_inc=%s image_inc=%s",
            identity.telegram_id,
            message_type,
            self._backend,
            bool(success),
            safe_message_increment,
            safe_image_increment,
        )

        users_upserted = 0
        history_inserted = 0
        try:
            users_upserted, history_inserted = await asyncio.to_thread(
                self._track_action_with_backend,
                self._backend,
                identity,
                message_type,
                user_message,
                bot_reply,
                model_used,
                success,
                safe_message_increment,
                safe_image_increment,
            )
        except Exception as exc:
            if self._backend == "postgres" and self._switch_to_http_backend(str(exc)):
                try:
                    users_upserted, history_inserted = await asyncio.to_thread(
                        self._track_action_with_backend,
                        "supabase_http",
                        identity,
                        message_type,
                        user_message,
                        bot_reply,
                        model_used,
                        success,
                        safe_message_increment,
                        safe_image_increment,
                    )
                except Exception as fallback_exc:
                    logger.exception(
                        "TRACKING FAILED user=%s message_type=%s backend=%s error=%s",
                        identity.telegram_id,
                        message_type,
                        self._backend,
                        fallback_exc,
                    )
                    raise
            else:
                logger.exception(
                    "TRACKING FAILED user=%s message_type=%s backend=%s error=%s",
                    identity.telegram_id,
                    message_type,
                    self._backend,
                    exc,
                )
                raise

        logger.info(
            "TRACKING SUCCESS user=%s message_type=%s backend=%s users_upserted=%s history_inserted=%s",
            identity.telegram_id,
            message_type,
            self._backend,
            users_upserted,
            history_inserted,
        )
        return users_upserted, history_inserted

    def _switch_to_http_backend(self, reason: str) -> bool:
        if self._supabase_client is None or self._supabase_config is None:
            return False
        previous_backend = self._backend
        self._backend = "supabase_http"
        self._disabled_reason = None
        logger.warning(
            "SUPABASE BACKEND FALLBACK | from=%s to=supabase_http reason=%s",
            previous_backend,
            reason,
        )
        return True

    def _verify_postgres_connection_sync(self) -> None:
        if self._postgres_config is None:
            raise RuntimeError("Postgres config is unavailable.")
        connection = open_postgres_connection(self._postgres_config)
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

    def _track_action_with_backend(
        self,
        backend: TrackingBackend,
        identity: TrackingIdentity,
        message_type: str,
        user_message: str,
        bot_reply: str | None,
        model_used: str | None,
        success: bool,
        message_increment: int,
        image_increment: int,
    ) -> tuple[int, int]:
        if backend == "postgres":
            return self._track_action_postgres_sync(
                identity=identity,
                message_type=message_type,
                user_message=user_message,
                bot_reply=bot_reply,
                model_used=model_used,
                success=success,
                message_increment=message_increment,
                image_increment=image_increment,
            )
        if backend == "supabase_http":
            return self._track_action_supabase_sync(
                identity=identity,
                message_type=message_type,
                user_message=user_message,
                bot_reply=bot_reply,
                model_used=model_used,
                success=success,
                message_increment=message_increment,
                image_increment=image_increment,
            )
        raise RuntimeError("No active tracking backend is available.")

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
        if self._postgres_config is None:
            raise RuntimeError("Postgres tracking backend is unavailable.")

        connection = open_postgres_connection(self._postgres_config)
        if connection is None:
            raise RuntimeError("Postgres connection is unavailable.")

        users_upserted = 0
        history_inserted = 0
        try:
            users_identifier = sql.Identifier(self._postgres_config.users_table)
            history_identifier = sql.Identifier(self._postgres_config.history_table)

            with connection:
                with connection.cursor() as cursor:
                    logger.info("UPSERT USER START user=%s backend=postgres", identity.telegram_id)
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
                    logger.info("UPSERT USER SUCCESS user=%s backend=postgres rows=%s", identity.telegram_id, users_upserted)

                    logger.info(
                        "INSERT HISTORY START user=%s backend=postgres message_type=%s",
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
                        "INSERT HISTORY SUCCESS user=%s backend=postgres rows=%s",
                        identity.telegram_id,
                        history_inserted,
                    )
            return users_upserted, history_inserted
        except Exception:
            logger.exception(
                "TRACKING FAILED user=%s message_type=%s backend=postgres",
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
        if self._supabase_client is None or self._supabase_config is None:
            raise RuntimeError("Supabase HTTP client is not initialized.")

        try:
            existing_user = self._fetch_existing_user_row(identity.telegram_id)
        except Exception as exc:
            logger.warning(
                "UPSERT USER PREFETCH FAILED user=%s backend=supabase_http error=%s",
                identity.telegram_id,
                exc,
                exc_info=True,
            )
            existing_user = None
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
        logger.info("UPSERT USER START user=%s backend=supabase_http", identity.telegram_id)
        user_response = self._supabase_client.table(self._supabase_config.users_table).upsert(
            user_payload,
            on_conflict="telegram_id",
            returning="representation",
            count="exact",
        ).execute()
        users_upserted = _response_rowcount(user_response)
        if users_upserted <= 0:
            raise RuntimeError("Supabase user upsert returned zero rows.")
        logger.info("UPSERT USER SUCCESS user=%s backend=supabase_http rows=%s", identity.telegram_id, users_upserted)

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
            "INSERT HISTORY START user=%s backend=supabase_http message_type=%s",
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
            "INSERT HISTORY SUCCESS user=%s backend=supabase_http rows=%s",
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
