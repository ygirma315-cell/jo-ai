from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Literal

from psycopg import sql
from supabase import Client, create_client

from bot.config import Settings, load_settings
from bot.services.postgres_client import PostgresConfig, build_postgres_config, open_postgres_connection
from bot.services.supabase_client import SupabaseConfig, build_supabase_config

logger = logging.getLogger(__name__)
TrackingBackend = Literal["postgres", "supabase_http", "disabled"]
FrontendSource = Literal["telegram_bot", "mini_app", "website", "api", "unknown"]
BLOCKED_ACCESS_STATUSES = frozenset({"blocked", "kicked"})


@dataclass(slots=True)
class TrackingIdentity:
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass(slots=True)
class TrackingMedia:
    media_type: str | None = None
    media_url: str | None = None
    storage_path: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    provider_source: str | None = None
    media_origin: str | None = None
    media_status: str | None = None
    media_error_reason: str | None = None


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


def _normalize_frontend_source(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "unknown"
    alias_map = {
        "telegram": "telegram_bot",
        "bot": "telegram_bot",
        "telegram_bot": "telegram_bot",
        "miniapp": "mini_app",
        "mini_app": "mini_app",
        "webapp": "mini_app",
        "website": "website",
        "web": "website",
        "api": "api",
    }
    return alias_map.get(normalized, normalized[:40])


def _normalize_feature_name(value: str | None, fallback: str | None = None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized:
        return normalized[:64]
    fallback_normalized = str(fallback or "").strip().lower()
    if fallback_normalized:
        return fallback_normalized[:64]
    return "unknown"


def _normalize_conversation_id(value: str | None, *, identity: TrackingIdentity, feature_used: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized[:120]
    return f"{identity.telegram_id}:{feature_used}:{datetime.now(timezone.utc).date().isoformat()}"


def _normalize_media_payload(media: TrackingMedia | None) -> TrackingMedia:
    if media is None:
        return TrackingMedia()
    return TrackingMedia(
        media_type=_clean_text(media.media_type, max_len=32),
        media_url=_clean_history_text(media.media_url, max_len=24_000),
        storage_path=_clean_text(media.storage_path, max_len=512),
        mime_type=_clean_text(media.mime_type, max_len=128),
        width=_safe_non_negative_int(media.width) if media.width is not None else None,
        height=_safe_non_negative_int(media.height) if media.height is not None else None,
        provider_source=_clean_text(media.provider_source, max_len=120),
        media_origin=_clean_text(media.media_origin, max_len=120),
        media_status=_clean_text(media.media_status, max_len=60),
        media_error_reason=_clean_history_text(media.media_error_reason, max_len=1000),
    )


def _referral_code_for_user(telegram_id: int) -> str:
    return str(max(1, int(telegram_id)))


def _sanitize_referral_code(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    normalized = normalized.replace("ref_", "").replace("ref-", "").strip()
    cleaned = "".join(ch for ch in normalized if ch.isalnum() or ch in {"_", "-"})
    if not cleaned:
        return None
    return cleaned[:64]


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
        frontend_source: str | None = None,
        feature_used: str | None = None,
        conversation_id: str | None = None,
        text_content: str | None = None,
        media: TrackingMedia | None = None,
        mark_started: bool = False,
        referral_code: str | None = None,
        started_via_referral: str | None = None,
    ) -> tuple[int, int]:
        if not self.enabled:
            logger.warning("TRACKING FAILED user=unknown error=tracking backend disabled reason=%s", self._disabled_reason)
            return 0, 0
        if identity is None or identity.telegram_id <= 0:
            logger.warning("TRACKING FAILED user=unknown error=missing telegram identity")
            return 0, 0

        safe_message_increment = max(0, int(message_increment))
        safe_image_increment = max(0, int(image_increment))
        safe_frontend_source = _normalize_frontend_source(frontend_source)
        safe_feature_used = _normalize_feature_name(feature_used, fallback=message_type)
        safe_conversation_id = _normalize_conversation_id(
            conversation_id,
            identity=identity,
            feature_used=safe_feature_used,
        )
        safe_text_content = _clean_history_text(text_content or user_message, max_len=16000)
        safe_media = _normalize_media_payload(media)
        safe_referral_code = _sanitize_referral_code(referral_code)
        safe_started_via_referral = _sanitize_referral_code(started_via_referral)

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
                safe_frontend_source,
                safe_feature_used,
                safe_conversation_id,
                safe_text_content,
                safe_media,
                bool(mark_started),
                safe_referral_code,
                safe_started_via_referral,
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
                        safe_frontend_source,
                        safe_feature_used,
                        safe_conversation_id,
                        safe_text_content,
                        safe_media,
                        bool(mark_started),
                        safe_referral_code,
                        safe_started_via_referral,
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
        frontend_source: str,
        feature_used: str,
        conversation_id: str,
        text_content: str | None,
        media: TrackingMedia,
        mark_started: bool,
        referral_code: str | None,
        started_via_referral: str | None,
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
                frontend_source=frontend_source,
                feature_used=feature_used,
                conversation_id=conversation_id,
                text_content=text_content,
                media=media,
                mark_started=mark_started,
                referral_code=referral_code,
                started_via_referral=started_via_referral,
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
                frontend_source=frontend_source,
                feature_used=feature_used,
                conversation_id=conversation_id,
                text_content=text_content,
                media=media,
                mark_started=mark_started,
                referral_code=referral_code,
                started_via_referral=started_via_referral,
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
        frontend_source: str,
        feature_used: str,
        conversation_id: str,
        text_content: str | None,
        media: TrackingMedia,
        mark_started: bool,
        referral_code: str | None,
        started_via_referral: str | None,
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
            referral_code_value = _sanitize_referral_code(referral_code) or _referral_code_for_user(identity.telegram_id)
            started_referral_value = _sanitize_referral_code(started_via_referral)
            message_type_value = _clean_text(message_type, max_len=64) or "unknown"

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
                                total_images,
                                has_started,
                                started_at,
                                is_active,
                                status,
                                is_blocked,
                                blocked_at,
                                last_delivery_error,
                                last_frontend_source,
                                referral_code,
                                started_via_referral,
                                referred_by
                            ) values (
                                %s, %s, %s, %s, timezone('utc', now()), %s, %s, %s,
                                case when %s then timezone('utc', now()) else null end,
                                true, 'active', false, null, null, %s, %s, %s,
                                (
                                    select telegram_id
                                    from {users}
                                    where referral_code = %s
                                      and telegram_id <> %s
                                    limit 1
                                )
                            )
                            on conflict (telegram_id) do update set
                                username = coalesce(excluded.username, u.username),
                                first_name = coalesce(excluded.first_name, u.first_name),
                                last_name = coalesce(excluded.last_name, u.last_name),
                                last_seen_at = timezone('utc', now()),
                                total_messages = coalesce(u.total_messages, 0) + excluded.total_messages,
                                total_images = coalesce(u.total_images, 0) + excluded.total_images,
                                has_started = coalesce(u.has_started, false) or coalesce(excluded.has_started, false),
                                started_at = coalesce(u.started_at, excluded.started_at),
                                is_active = case when coalesce(u.is_blocked, false) then false else true end,
                                status = case
                                    when coalesce(u.is_blocked, false) then coalesce(nullif(u.status, ''), 'blocked')
                                    else 'active'
                                end,
                                is_blocked = coalesce(u.is_blocked, false),
                                blocked_at = case
                                    when coalesce(u.is_blocked, false) then coalesce(u.blocked_at, timezone('utc', now()))
                                    else null
                                end,
                                last_delivery_error = case
                                    when coalesce(u.is_blocked, false) then u.last_delivery_error
                                    else null
                                end,
                                last_frontend_source = coalesce(excluded.last_frontend_source, u.last_frontend_source),
                                referral_code = excluded.referral_code,
                                started_via_referral = coalesce(u.started_via_referral, excluded.started_via_referral),
                                referred_by = coalesce(u.referred_by, excluded.referred_by)
                            """
                        ).format(users=users_identifier),
                        (
                            identity.telegram_id,
                            _clean_text(identity.username, max_len=128),
                            _clean_text(identity.first_name, max_len=128),
                            _clean_text(identity.last_name, max_len=128),
                            message_increment,
                            image_increment,
                            bool(mark_started),
                            bool(mark_started),
                            _clean_text(frontend_source, max_len=40),
                            referral_code_value,
                            started_referral_value,
                            started_referral_value,
                            identity.telegram_id,
                        ),
                    )
                    users_upserted = max(0, int(cursor.rowcount or 0))
                    logger.info("UPSERT USER SUCCESS user=%s backend=postgres rows=%s", identity.telegram_id, users_upserted)

                    if bool(mark_started) and started_referral_value:
                        try:
                            cursor.execute(
                                sql.SQL(
                                    """
                                    insert into public.referrals (
                                        referral_code,
                                        inviter_telegram_id,
                                        invitee_telegram_id,
                                        frontend_source,
                                        created_at
                                    )
                                    select
                                        %s,
                                        inviter.telegram_id,
                                        %s,
                                        %s,
                                        timezone('utc', now())
                                    from {users} inviter
                                    where inviter.referral_code = %s
                                      and inviter.telegram_id <> %s
                                    on conflict (invitee_telegram_id) do nothing
                                    """
                                ).format(users=users_identifier),
                                (
                                    started_referral_value,
                                    identity.telegram_id,
                                    _clean_text(frontend_source, max_len=40),
                                    started_referral_value,
                                    identity.telegram_id,
                                ),
                            )
                        except Exception:
                            logger.warning(
                                "REFERRAL INSERT FAILED user=%s backend=postgres",
                                identity.telegram_id,
                                exc_info=True,
                            )

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
                                created_at,
                                frontend_source,
                                feature_used,
                                conversation_id,
                                text_content,
                                media_type,
                                media_url,
                                storage_path,
                                mime_type,
                                media_width,
                                media_height,
                                provider_source,
                                media_origin,
                                media_status,
                                media_error_reason
                            ) values (
                                %s, %s, %s, %s, %s, %s, timezone('utc', now()),
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            """
                        ).format(history=history_identifier),
                        (
                            identity.telegram_id,
                            message_type_value,
                            _clean_history_text(user_message, max_len=16000),
                            _clean_history_text(bot_reply, max_len=16000),
                            _clean_text(model_used, max_len=256),
                            bool(success),
                            _clean_text(frontend_source, max_len=40),
                            _clean_text(feature_used, max_len=64),
                            _clean_text(conversation_id, max_len=120),
                            _clean_history_text(text_content or user_message, max_len=16000),
                            _clean_text(media.media_type, max_len=32),
                            _clean_history_text(media.media_url, max_len=24_000),
                            _clean_text(media.storage_path, max_len=512),
                            _clean_text(media.mime_type, max_len=128),
                            media.width,
                            media.height,
                            _clean_text(media.provider_source, max_len=120),
                            _clean_text(media.media_origin, max_len=120),
                            _clean_text(media.media_status, max_len=60),
                            _clean_history_text(media.media_error_reason, max_len=1000),
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
        frontend_source: str,
        feature_used: str,
        conversation_id: str,
        text_content: str | None,
        media: TrackingMedia,
        mark_started: bool,
        referral_code: str | None,
        started_via_referral: str | None,
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
        existing_has_started = bool(existing_user.get("has_started")) if existing_user else False
        existing_started_at = existing_user.get("started_at") if existing_user else None
        existing_referred_by = _safe_non_negative_int(existing_user.get("referred_by") if existing_user else 0)
        existing_is_blocked = bool(existing_user.get("is_blocked")) if existing_user else False
        existing_status = str(existing_user.get("status") or "").strip().lower() if existing_user else ""
        existing_blocked_at = existing_user.get("blocked_at") if existing_user else None
        _ = referral_code
        effective_referral_code = _referral_code_for_user(identity.telegram_id)
        started_referral_value = _sanitize_referral_code(started_via_referral)
        resolved_referred_by = existing_referred_by if existing_referred_by > 0 else 0
        if started_referral_value and (resolved_referred_by <= 0):
            resolved_referred_by = self._resolve_referrer_telegram_id(started_referral_value, identity.telegram_id) or 0

        user_is_restricted = existing_is_blocked or existing_status in BLOCKED_ACCESS_STATUSES
        resolved_is_blocked = bool(user_is_restricted)
        resolved_status = "kicked" if existing_status == "kicked" else ("blocked" if user_is_restricted else "active")
        resolved_blocked_at = existing_blocked_at or (_utc_now_iso() if user_is_restricted else None)
        resolved_is_active = False if user_is_restricted else True

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
            "has_started": bool(mark_started or existing_has_started),
            "started_at": existing_started_at or (_utc_now_iso() if mark_started else None),
            "is_active": resolved_is_active,
            "status": resolved_status,
            "is_blocked": resolved_is_blocked,
            "blocked_at": resolved_blocked_at,
            "last_delivery_error": existing_user.get("last_delivery_error") if user_is_restricted and existing_user else None,
            "last_frontend_source": _clean_text(frontend_source, max_len=40),
            "referral_code": effective_referral_code,
            "started_via_referral": started_referral_value,
            "referred_by": resolved_referred_by or None,
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

        if bool(mark_started) and started_referral_value and resolved_referred_by > 0:
            try:
                referral_payload = {
                    "referral_code": started_referral_value,
                    "inviter_telegram_id": resolved_referred_by,
                    "invitee_telegram_id": identity.telegram_id,
                    "frontend_source": _clean_text(frontend_source, max_len=40),
                    "created_at": _utc_now_iso(),
                }
                self._supabase_client.table("referrals").upsert(
                    referral_payload,
                    on_conflict="invitee_telegram_id",
                    returning="minimal",
                ).execute()
            except Exception:
                logger.warning(
                    "REFERRAL INSERT FAILED user=%s backend=supabase_http",
                    identity.telegram_id,
                    exc_info=True,
                )

        history_payload = {
            "telegram_id": identity.telegram_id,
            "message_type": _clean_text(message_type, max_len=64) or "unknown",
            "user_message": _clean_history_text(user_message, max_len=16000),
            "bot_reply": _clean_history_text(bot_reply, max_len=16000),
            "model_used": _clean_text(model_used, max_len=256),
            "success": bool(success),
            "created_at": _utc_now_iso(),
            "frontend_source": _clean_text(frontend_source, max_len=40),
            "feature_used": _clean_text(feature_used, max_len=64),
            "conversation_id": _clean_text(conversation_id, max_len=120),
            "text_content": _clean_history_text(text_content or user_message, max_len=16000),
            "media_type": _clean_text(media.media_type, max_len=32),
            "media_url": _clean_history_text(media.media_url, max_len=24_000),
            "storage_path": _clean_text(media.storage_path, max_len=512),
            "mime_type": _clean_text(media.mime_type, max_len=128),
            "media_width": media.width,
            "media_height": media.height,
            "provider_source": _clean_text(media.provider_source, max_len=120),
            "media_origin": _clean_text(media.media_origin, max_len=120),
            "media_status": _clean_text(media.media_status, max_len=60),
            "media_error_reason": _clean_history_text(media.media_error_reason, max_len=1000),
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
        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return None
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                select
                                    username,
                                    first_name,
                                    last_name,
                                    total_messages,
                                    total_images,
                                    has_started,
                                    started_at,
                                    referred_by,
                                    referral_code,
                                    started_via_referral,
                                    status,
                                    is_blocked,
                                    blocked_at,
                                    unreachable_count,
                                    engagement_count
                                from {users}
                                where telegram_id = %s
                                limit 1
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            (telegram_id,),
                        )
                        row = cursor.fetchone()
                if row:
                    return {
                        "username": row[0],
                        "first_name": row[1],
                        "last_name": row[2],
                        "total_messages": row[3],
                        "total_images": row[4],
                        "has_started": row[5],
                        "started_at": row[6],
                        "referred_by": row[7],
                        "referral_code": row[8],
                        "started_via_referral": row[9],
                        "status": row[10],
                        "is_blocked": row[11],
                        "blocked_at": row[12],
                        "unreachable_count": row[13],
                        "engagement_count": row[14],
                    }
            except Exception:
                logger.warning("USER PREFETCH FAILED backend=postgres user=%s", telegram_id, exc_info=True)
            finally:
                with suppress(Exception):
                    connection.close()
            return None

        if self._supabase_client is None or self._supabase_config is None:
            return None
        response = self._supabase_client.table(self._supabase_config.users_table).select(
            (
                "username,first_name,last_name,total_messages,total_images,"
                "has_started,started_at,referred_by,referral_code,started_via_referral,"
                "status,is_blocked,blocked_at,unreachable_count,engagement_count,last_delivery_error"
            ),
            count="exact",
        ).eq("telegram_id", telegram_id).limit(1).execute()
        data = getattr(response, "data", None)
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first
        return None

    def _resolve_referrer_telegram_id(self, referral_code: str, invitee_telegram_id: int) -> int | None:
        if not referral_code:
            return None
        normalized_code = _sanitize_referral_code(referral_code)
        if not normalized_code:
            return None
        numeric_referrer = _safe_non_negative_int(normalized_code, default=0)
        if numeric_referrer > 0 and numeric_referrer != invitee_telegram_id:
            return numeric_referrer

        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return None
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                select telegram_id
                                from {users}
                                where referral_code = %s
                                  and telegram_id <> %s
                                limit 1
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            (normalized_code, invitee_telegram_id),
                        )
                        row = cursor.fetchone()
                if not row:
                    return None
                resolved = _safe_non_negative_int(row[0], default=0)
                return resolved or None
            except Exception:
                logger.warning(
                    "REFERRAL LOOKUP FAILED backend=postgres code=%s",
                    normalized_code,
                    exc_info=True,
                )
                return None
            finally:
                with suppress(Exception):
                    connection.close()

        if self._supabase_client is None or self._supabase_config is None:
            return None
        try:
            response = (
                self._supabase_client.table(self._supabase_config.users_table)
                .select("telegram_id")
                .eq("referral_code", normalized_code)
                .neq("telegram_id", invitee_telegram_id)
                .limit(1)
                .execute()
            )
            data = getattr(response, "data", None)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return _safe_non_negative_int(data[0].get("telegram_id"), default=0) or None
        except Exception:
            logger.warning(
                "REFERRAL LOOKUP FAILED backend=supabase_http code=%s",
                normalized_code,
                exc_info=True,
            )
        return None

    async def is_user_access_restricted(self, telegram_id: int) -> bool:
        user_id = int(telegram_id or 0)
        if user_id <= 0 or not self.enabled:
            return False
        return await asyncio.to_thread(self._is_user_access_restricted_sync, user_id)

    async def mark_delivery_failure(self, telegram_id: int, reason: str, *, blocked: bool = False) -> None:
        user_id = int(telegram_id or 0)
        if user_id <= 0 or not self.enabled:
            return
        safe_reason = _clean_history_text(reason, max_len=500) or "delivery_failed"
        await asyncio.to_thread(self._mark_delivery_failure_sync, user_id, safe_reason, bool(blocked))

    async def mark_delivery_success(self, telegram_id: int) -> None:
        user_id = int(telegram_id or 0)
        if user_id <= 0 or not self.enabled:
            return
        await asyncio.to_thread(self._mark_delivery_success_sync, user_id)

    async def fetch_engagement_candidates(
        self,
        *,
        inactivity_minutes: int,
        cooldown_minutes: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return await asyncio.to_thread(
            self._fetch_engagement_candidates_sync,
            max(1, int(inactivity_minutes)),
            max(1, int(cooldown_minutes)),
            max(1, min(500, int(limit))),
        )

    async def mark_engagement_sent(self, telegram_id: int) -> None:
        user_id = int(telegram_id or 0)
        if user_id <= 0 or not self.enabled:
            return
        await asyncio.to_thread(self._mark_engagement_sent_sync, user_id)

    async def ensure_referral_code(
        self,
        *,
        identity: TrackingIdentity,
        frontend_source: str = "telegram_bot",
    ) -> str:
        if not self.enabled:
            return _referral_code_for_user(identity.telegram_id)
        return await asyncio.to_thread(self._ensure_referral_code_sync, identity, frontend_source)

    def _is_user_access_restricted_sync(self, telegram_id: int) -> bool:
        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return False
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                select is_blocked, status
                                from {users}
                                where telegram_id = %s
                                limit 1
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            (telegram_id,),
                        )
                        row = cursor.fetchone()
                if not row:
                    return False
                is_blocked = bool(row[0])
                status = str(row[1] or "").strip().lower()
                return bool(is_blocked or status in BLOCKED_ACCESS_STATUSES)
            except Exception:
                logger.warning(
                    "USER ACCESS CHECK FAILED backend=postgres user=%s",
                    telegram_id,
                    exc_info=True,
                )
                return False
            finally:
                with suppress(Exception):
                    connection.close()

        if self._supabase_client is None or self._supabase_config is None:
            return False
        try:
            response = (
                self._supabase_client.table(self._supabase_config.users_table)
                .select("is_blocked,status")
                .eq("telegram_id", telegram_id)
                .limit(1)
                .execute()
            )
            data = getattr(response, "data", None)
            if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                return False
            row = data[0]
            is_blocked = bool(row.get("is_blocked"))
            status = str(row.get("status") or "").strip().lower()
            return bool(is_blocked or status in BLOCKED_ACCESS_STATUSES)
        except Exception:
            logger.warning(
                "USER ACCESS CHECK FAILED backend=supabase_http user=%s",
                telegram_id,
                exc_info=True,
            )
            return False

    def _mark_delivery_failure_sync(self, telegram_id: int, reason: str, blocked: bool) -> None:
        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                update {users}
                                set
                                    is_active = false,
                                    status = %s,
                                    is_blocked = %s,
                                    blocked_at = case when %s then timezone('utc', now()) else blocked_at end,
                                    unreachable_count = coalesce(unreachable_count, 0) + 1,
                                    last_delivery_error = %s
                                where telegram_id = %s
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            ("blocked" if blocked else "unreachable", blocked, blocked, reason, telegram_id),
                        )
            except Exception:
                logger.warning("DELIVERY FAILURE UPDATE FAILED backend=postgres user=%s", telegram_id, exc_info=True)
            finally:
                with suppress(Exception):
                    connection.close()
            return

        if self._supabase_client is None or self._supabase_config is None:
            return
        try:
            existing = self._fetch_existing_user_row(telegram_id) or {}
            next_unreachable = _safe_non_negative_int(existing.get("unreachable_count"), default=0) + 1
            self._supabase_client.table(self._supabase_config.users_table).update(
                {
                    "is_active": False,
                    "status": "blocked" if blocked else "unreachable",
                    "is_blocked": bool(blocked),
                    "blocked_at": _utc_now_iso() if blocked else None,
                    "unreachable_count": next_unreachable,
                    "last_delivery_error": reason,
                }
            ).eq("telegram_id", telegram_id).execute()
        except Exception:
            logger.warning("DELIVERY FAILURE UPDATE FAILED backend=supabase_http user=%s", telegram_id, exc_info=True)

    def _mark_delivery_success_sync(self, telegram_id: int) -> None:
        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                update {users}
                                set
                                    is_active = case when coalesce(is_blocked, false) then false else true end,
                                    status = case
                                        when coalesce(is_blocked, false) then coalesce(nullif(status, ''), 'blocked')
                                        else 'active'
                                    end,
                                    blocked_at = case
                                        when coalesce(is_blocked, false) then blocked_at
                                        else null
                                    end,
                                    last_delivery_error = null,
                                    last_seen_at = timezone('utc', now())
                                where telegram_id = %s
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            (telegram_id,),
                        )
            except Exception:
                logger.warning("DELIVERY SUCCESS UPDATE FAILED backend=postgres user=%s", telegram_id, exc_info=True)
            finally:
                with suppress(Exception):
                    connection.close()
            return

        if self._supabase_client is None or self._supabase_config is None:
            return
        try:
            existing = self._fetch_existing_user_row(telegram_id) or {}
            user_is_blocked = bool(existing.get("is_blocked"))
            current_status = str(existing.get("status") or "").strip().lower()
            resolved_status = (
                "kicked"
                if current_status == "kicked"
                else ("blocked" if user_is_blocked else "active")
            )
            self._supabase_client.table(self._supabase_config.users_table).update(
                {
                    "is_active": False if user_is_blocked else True,
                    "status": resolved_status,
                    "blocked_at": existing.get("blocked_at") if user_is_blocked else None,
                    "last_delivery_error": None,
                    "last_seen_at": _utc_now_iso(),
                }
            ).eq("telegram_id", telegram_id).execute()
        except Exception:
            logger.warning("DELIVERY SUCCESS UPDATE FAILED backend=supabase_http user=%s", telegram_id, exc_info=True)

    def _fetch_engagement_candidates_sync(
        self,
        inactivity_minutes: int,
        cooldown_minutes: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        inactive_cutoff_iso = (now - timedelta(minutes=inactivity_minutes)).isoformat()
        cooldown_cutoff = now - timedelta(minutes=cooldown_minutes)
        items: list[dict[str, Any]] = []

        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return []
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                select
                                    telegram_id,
                                    username,
                                    first_name,
                                    last_name,
                                    last_seen_at,
                                    last_engagement_sent_at
                                from {users}
                                where coalesce(has_started, false) = true
                                  and coalesce(is_active, true) = true
                                  and coalesce(is_blocked, false) = false
                                  and coalesce(last_seen_at, timezone('utc', now())) <= %s
                                order by last_seen_at asc nulls first
                                limit %s
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            (inactive_cutoff_iso, limit * 4),
                        )
                        rows = cursor.fetchall()
                for row in rows:
                    if len(items) >= limit:
                        break
                    last_engagement_sent_at = row[5]
                    if isinstance(last_engagement_sent_at, datetime):
                        if last_engagement_sent_at.tzinfo is None:
                            last_engagement_sent_at = last_engagement_sent_at.replace(tzinfo=timezone.utc)
                        if last_engagement_sent_at.astimezone(timezone.utc) > cooldown_cutoff:
                            continue
                    items.append(
                        {
                            "telegram_id": _safe_non_negative_int(row[0], default=0),
                            "username": _clean_text(row[1], max_len=128),
                            "first_name": _clean_text(row[2], max_len=128),
                            "last_name": _clean_text(row[3], max_len=128),
                        }
                    )
                return [item for item in items if int(item.get("telegram_id") or 0) > 0]
            except Exception:
                logger.warning("ENGAGEMENT CANDIDATE QUERY FAILED backend=postgres", exc_info=True)
                return []
            finally:
                with suppress(Exception):
                    connection.close()

        if self._supabase_client is None or self._supabase_config is None:
            return []
        try:
            response = (
                self._supabase_client.table(self._supabase_config.users_table)
                .select(
                    "telegram_id,username,first_name,last_name,last_seen_at,last_engagement_sent_at,has_started,is_active,is_blocked"
                )
                .lte("last_seen_at", inactive_cutoff_iso)
                .limit(limit * 4)
                .execute()
            )
            rows = getattr(response, "data", None)
            if not isinstance(rows, list):
                return []
            for row in rows:
                if len(items) >= limit:
                    break
                if not isinstance(row, dict):
                    continue
                if not bool(row.get("has_started")):
                    continue
                if row.get("is_active") is False:
                    continue
                if bool(row.get("is_blocked")):
                    continue
                last_sent = row.get("last_engagement_sent_at")
                if last_sent:
                    try:
                        parsed = datetime.fromisoformat(str(last_sent).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        if parsed.astimezone(timezone.utc) > cooldown_cutoff:
                            continue
                    except Exception:
                        pass
                telegram_id = _safe_non_negative_int(row.get("telegram_id"), default=0)
                if telegram_id <= 0:
                    continue
                items.append(
                    {
                        "telegram_id": telegram_id,
                        "username": _clean_text(row.get("username"), max_len=128),
                        "first_name": _clean_text(row.get("first_name"), max_len=128),
                        "last_name": _clean_text(row.get("last_name"), max_len=128),
                    }
                )
            return items
        except Exception:
            logger.warning("ENGAGEMENT CANDIDATE QUERY FAILED backend=supabase_http", exc_info=True)
            return []

    def _mark_engagement_sent_sync(self, telegram_id: int) -> None:
        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is None:
                return
            try:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                """
                                update {users}
                                set
                                    last_engagement_sent_at = timezone('utc', now()),
                                    engagement_count = coalesce(engagement_count, 0) + 1
                                where telegram_id = %s
                                """
                            ).format(users=sql.Identifier(self._postgres_config.users_table)),
                            (telegram_id,),
                        )
            except Exception:
                logger.warning("ENGAGEMENT MARK FAILED backend=postgres user=%s", telegram_id, exc_info=True)
            finally:
                with suppress(Exception):
                    connection.close()
            return

        if self._supabase_client is None or self._supabase_config is None:
            return
        try:
            existing = self._fetch_existing_user_row(telegram_id) or {}
            next_count = _safe_non_negative_int(existing.get("engagement_count"), default=0) + 1
            self._supabase_client.table(self._supabase_config.users_table).update(
                {
                    "last_engagement_sent_at": _utc_now_iso(),
                    "engagement_count": next_count,
                }
            ).eq("telegram_id", telegram_id).execute()
        except Exception:
            logger.warning("ENGAGEMENT MARK FAILED backend=supabase_http user=%s", telegram_id, exc_info=True)

    def _ensure_referral_code_sync(self, identity: TrackingIdentity, frontend_source: str) -> str:
        existing = self._fetch_existing_user_row(identity.telegram_id) or {}
        current_code = _sanitize_referral_code(existing.get("referral_code"))
        referral_code_value = _referral_code_for_user(identity.telegram_id)
        if current_code == referral_code_value:
            return current_code
        if self._backend == "postgres" and self._postgres_config is not None:
            connection = open_postgres_connection(self._postgres_config)
            if connection is not None:
                try:
                    with connection:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                sql.SQL(
                                    """
                                    insert into {users} (
                                        telegram_id,
                                        username,
                                        first_name,
                                        last_name,
                                        first_seen_at,
                                        last_seen_at,
                                        referral_code,
                                        last_frontend_source
                                    ) values (
                                        %s, %s, %s, %s, timezone('utc', now()), timezone('utc', now()), %s, %s
                                    )
                                    on conflict (telegram_id) do update set
                                        referral_code = excluded.referral_code,
                                        username = coalesce(excluded.username, {users}.username),
                                        first_name = coalesce(excluded.first_name, {users}.first_name),
                                        last_name = coalesce(excluded.last_name, {users}.last_name),
                                        last_frontend_source = coalesce(excluded.last_frontend_source, {users}.last_frontend_source)
                                    """
                                ).format(users=sql.Identifier(self._postgres_config.users_table)),
                                (
                                    identity.telegram_id,
                                    _clean_text(identity.username, max_len=128),
                                    _clean_text(identity.first_name, max_len=128),
                                    _clean_text(identity.last_name, max_len=128),
                                    referral_code_value,
                                    _clean_text(frontend_source, max_len=40),
                                ),
                            )
                except Exception:
                    logger.warning("REFERRAL CODE UPSERT FAILED backend=postgres user=%s", identity.telegram_id, exc_info=True)
                finally:
                    with suppress(Exception):
                        connection.close()
            return referral_code_value

        if self._supabase_client is None or self._supabase_config is None:
            return referral_code_value
        try:
            self._supabase_client.table(self._supabase_config.users_table).upsert(
                {
                    "telegram_id": identity.telegram_id,
                    "username": _clean_text(identity.username, max_len=128),
                    "first_name": _clean_text(identity.first_name, max_len=128),
                    "last_name": _clean_text(identity.last_name, max_len=128),
                    "first_seen_at": _utc_now_iso(),
                    "last_seen_at": _utc_now_iso(),
                    "referral_code": referral_code_value,
                    "last_frontend_source": _clean_text(frontend_source, max_len=40),
                },
                on_conflict="telegram_id",
                returning="minimal",
            ).execute()
        except Exception:
            logger.warning("REFERRAL CODE UPSERT FAILED backend=supabase_http user=%s", identity.telegram_id, exc_info=True)
        return referral_code_value
