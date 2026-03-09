from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging

from psycopg import sql

from bot.config import Settings, load_settings
from bot.services.postgres_client import PostgresConfig, build_postgres_config, open_postgres_connection

logger = logging.getLogger(__name__)


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


class SupabaseTrackingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()
        self._postgres_config: PostgresConfig | None = build_postgres_config(self._settings)
        if self._postgres_config is None:
            logger.warning(
                "Tracking disabled: SUPABASE_DB_URL is missing or invalid."
            )
        else:
            logger.info(
                "Tracking initialized | users_table=%s history_table=%s",
                self._postgres_config.users_table,
                self._postgres_config.history_table,
            )

    @property
    def enabled(self) -> bool:
        return self._postgres_config is not None

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

        logger.info(
            "Tracking start | telegram_id=%s message_type=%s success=%s message_inc=%s image_inc=%s",
            identity.telegram_id,
            message_type,
            bool(success),
            max(0, int(message_increment)),
            max(0, int(image_increment)),
        )

        users_upserted, history_inserted = await asyncio.to_thread(
            self._track_action_sync,
            identity,
            message_type,
            user_message,
            bot_reply,
            model_used,
            success,
            max(0, int(message_increment)),
            max(0, int(image_increment)),
        )
        logger.info(
            "Tracking success | telegram_id=%s message_type=%s users_upserted=%s history_inserted=%s",
            identity.telegram_id,
            message_type,
            users_upserted,
            history_inserted,
        )

    def _track_action_sync(
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
        if not self.enabled:
            raise RuntimeError("Tracking is disabled.")
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
