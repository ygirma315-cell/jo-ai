from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from urllib.parse import quote

from supabase import Client, create_client

from bot.config import Settings, load_settings
from bot.services.supabase_client import SupabaseConfig, build_supabase_config

logger = logging.getLogger(__name__)
IMAGE_MESSAGE_TYPES = frozenset({"image", "vision"})
AUDIO_MESSAGE_TYPES = frozenset({"tts", "voice", "audio"})
MEDIA_MESSAGE_TYPES = frozenset({"image", "vision", "video"})


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _response_rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _response_count(response: Any) -> int:
    count = getattr(response, "count", None)
    if isinstance(count, int):
        return max(0, count)
    return len(_response_rows(response))


def _truncate_text(value: Any, max_len: int = 140) -> str:
    raw = str(value or "").strip()
    if len(raw) <= max_len:
        return raw
    return f"{raw[: max_len - 1].rstrip()}..."


def _parse_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _start_of_utc_day(day: datetime | None = None) -> datetime:
    current = day.astimezone(timezone.utc) if day else datetime.now(timezone.utc)
    return datetime(current.year, current.month, current.day, tzinfo=timezone.utc)


def _media_preview_ref(media_url: Any, storage_path: Any) -> str | None:
    raw_media_url = str(media_url or "").strip()
    if raw_media_url:
        return raw_media_url
    raw_storage_path = str(storage_path or "").strip()
    if not raw_storage_path:
        return None
    if raw_storage_path.startswith("telegram_file:"):
        return f"/api/admin/media/proxy?ref={quote(raw_storage_path, safe='')}"
    if raw_storage_path.startswith("local_file:"):
        filename = raw_storage_path.split(":", maxsplit=1)[1].strip()
        if filename:
            return f"/media/{quote(filename, safe='')}"
    return raw_storage_path


class SupabaseAdminService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()
        self._config: SupabaseConfig | None = build_supabase_config(self._settings)
        self._client: Client | None = None
        self._disabled_reason: str | None = None

        if self._config is None:
            self._disabled_reason = "Supabase config is missing or invalid."
            return

        try:
            self._client = create_client(self._config.url, self._config.api_key)
        except Exception as exc:
            self._disabled_reason = f"Failed to initialize Supabase client: {exc}"
            logger.exception("ADMIN SERVICE INIT FAILED | error=%s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None and self._config is not None

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def _ensure_ready(self) -> tuple[Client, SupabaseConfig]:
        if self._client is None or self._config is None:
            raise RuntimeError(self._disabled_reason or "Admin service is not configured.")
        return self._client, self._config

    def _admin_auth_config(self) -> dict[str, Any]:
        client, _config = self._ensure_ready()
        try:
            response = (
                client.table("admin_config")
                .select("value_json")
                .eq("config_key", "admin_auth")
                .limit(1)
                .execute()
            )
        except Exception:
            logger.warning("Admin auth config query failed; falling back to settings.", exc_info=True)
            return {}
        rows = _response_rows(response)
        if not rows:
            return {}
        value_json = rows[0].get("value_json")
        if isinstance(value_json, dict):
            return value_json
        return {}

    def resolve_admin_owner_telegram_id(self) -> int | None:
        owner_candidates: list[Any] = []
        if self.enabled:
            config = self._admin_auth_config()
            owner_candidates.extend(
                [
                    config.get("owner_telegram_id"),
                    config.get("admin_telegram_id"),
                ]
            )
        owner_candidates.append(self._settings.admin_dashboard_owner_telegram_id)
        for value in owner_candidates:
            candidate = _safe_int(value)
            if candidate > 0:
                return candidate
        allowlist = [int(value) for value in self._settings.admin_dashboard_allowlist_telegram_ids if int(value) > 0]
        return allowlist[0] if allowlist else None

    def is_known_telegram_user(self, telegram_id: int) -> bool:
        if int(telegram_id or 0) <= 0:
            return False
        client, config = self._ensure_ready()
        try:
            response = (
                client.table(config.users_table)
                .select("telegram_id")
                .eq("telegram_id", int(telegram_id))
                .limit(1)
                .execute()
            )
            return len(_response_rows(response)) > 0
        except Exception:
            logger.warning("Admin known-user lookup failed for user=%s", telegram_id, exc_info=True)
            return False

    def _fetch_all_user_totals(self, max_rows: int = 50000) -> list[dict[str, Any]]:
        client, config = self._ensure_ready()
        page_size = 1000
        offset = 0
        rows: list[dict[str, Any]] = []

        while offset < max_rows:
            response = (
                client.table(config.users_table)
                .select(
                    (
                        "telegram_id,total_messages,total_images,first_seen_at,last_seen_at,"
                        "has_started,is_active,is_blocked,status,referred_by,unreachable_count"
                    )
                )
                .order("telegram_id", desc=False)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            chunk = _response_rows(response)
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
            offset += page_size
        if len(rows) >= max_rows:
            logger.warning("ADMIN QUERY CAP HIT | table=users max_rows=%s", max_rows)
        return rows

    def _fetch_history_since(self, start_iso: str, columns: str, max_rows: int = 60000) -> list[dict[str, Any]]:
        client, config = self._ensure_ready()
        page_size = 1000
        offset = 0
        rows: list[dict[str, Any]] = []

        while offset < max_rows:
            response = (
                client.table(config.history_table)
                .select(columns)
                .gte("created_at", start_iso)
                .order("created_at", desc=False)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            chunk = _response_rows(response)
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
            offset += page_size
        if len(rows) >= max_rows:
            logger.warning(
                "ADMIN QUERY CAP HIT | table=history max_rows=%s start_iso=%s columns=%s",
                max_rows,
                start_iso,
                columns,
            )
        return rows

    def _load_users_map(self, telegram_ids: list[int]) -> dict[int, dict[str, Any]]:
        client, config = self._ensure_ready()
        unique_ids = sorted({int(item) for item in telegram_ids if int(item) != 0})
        if not unique_ids:
            return {}

        query = client.table(config.users_table).select(
            (
                "telegram_id,username,first_name,last_name,total_messages,total_images,last_seen_at,first_seen_at,"
                "has_started,started_at,is_active,status,is_blocked,unreachable_count,last_delivery_error,"
                "referral_code,referred_by,started_via_referral,last_engagement_sent_at,engagement_count"
            )
        )
        if len(unique_ids) == 1:
            response = query.eq("telegram_id", unique_ids[0]).execute()
        else:
            response = query.in_("telegram_id", unique_ids).execute()

        mapping: dict[int, dict[str, Any]] = {}
        for row in _response_rows(response):
            telegram_id = _safe_int(row.get("telegram_id"))
            if telegram_id != 0:
                mapping[telegram_id] = row
        return mapping

    def _search_user_ids(self, term: str, max_ids: int = 500) -> list[int]:
        client, config = self._ensure_ready()
        normalized = str(term or "").strip().lstrip("@")
        if not normalized:
            return []

        like_value = f"%{normalized}%"
        ids: set[int] = set()
        for field in ("username", "first_name", "last_name"):
            response = (
                client.table(config.users_table)
                .select("telegram_id")
                .ilike(field, like_value)
                .limit(max_ids)
                .execute()
            )
            for row in _response_rows(response):
                telegram_id = _safe_int(row.get("telegram_id"))
                if telegram_id != 0:
                    ids.add(telegram_id)
            if len(ids) >= max_ids:
                break

        return sorted(ids)[:max_ids]

    def _build_trends(self, rows: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
        utc_today = _start_of_utc_day()
        start_day = utc_today - timedelta(days=days - 1)
        labels: list[str] = []
        keys: list[str] = []
        day_events: dict[str, int] = {}
        day_images: dict[str, int] = {}
        day_audio: dict[str, int] = {}
        day_active_users: dict[str, set[int]] = {}

        for index in range(days):
            current_day = start_day + timedelta(days=index)
            key = current_day.date().isoformat()
            keys.append(key)
            labels.append(current_day.strftime("%b %d"))
            day_events[key] = 0
            day_images[key] = 0
            day_audio[key] = 0
            day_active_users[key] = set()

        for row in rows:
            created_at = _parse_timestamp(row.get("created_at"))
            if created_at is None:
                continue
            key = created_at.date().isoformat()
            if key not in day_events:
                continue

            message_type = str(row.get("message_type") or "").strip().lower()
            day_events[key] += 1
            if message_type in IMAGE_MESSAGE_TYPES:
                day_images[key] += 1
            if message_type in AUDIO_MESSAGE_TYPES:
                day_audio[key] += 1

            telegram_id = _safe_int(row.get("telegram_id"))
            if telegram_id != 0:
                day_active_users[key].add(telegram_id)

        total_messages_series: list[int] = []
        image_series: list[int] = []
        audio_series: list[int] = []
        active_users_series: list[int] = []
        for key in keys:
            total_events = day_events[key]
            total_images = day_images[key]
            total_audio = day_audio[key]
            total_messages_series.append(max(0, total_events - total_images))
            image_series.append(total_images)
            audio_series.append(total_audio)
            active_users_series.append(len(day_active_users[key]))

        return {
            "labels": labels,
            "messages": total_messages_series,
            "images": image_series,
            "audio": audio_series,
            "active_users": active_users_series,
        }

    def get_overview(self, days: int = 14) -> dict[str, Any]:
        client, config = self._ensure_ready()
        window_days = _clamp(days, 7, 90)
        utc_today = _start_of_utc_day()
        today_iso = utc_today.isoformat()

        total_users_response = client.table(config.users_table).select("telegram_id", count="exact").limit(1).execute()
        active_users_today_response = (
            client.table(config.users_table).select("telegram_id", count="exact").gte("last_seen_at", today_iso).limit(1).execute()
        )
        total_audio_response = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(AUDIO_MESSAGE_TYPES))
            .limit(1)
            .execute()
        )

        totals_rows = self._fetch_all_user_totals()
        total_users = len(totals_rows)
        total_messages = sum(max(0, _safe_int(item.get("total_messages"))) for item in totals_rows)
        total_images = sum(max(0, _safe_int(item.get("total_images"))) for item in totals_rows)
        total_started_users = sum(1 for row in totals_rows if bool(row.get("has_started")))
        active_users = sum(
            1
            for row in totals_rows
            if bool(row.get("is_active", True)) and not bool(row.get("is_blocked"))
        )
        blocked_users = sum(
            1
            for row in totals_rows
            if bool(row.get("is_blocked")) or str(row.get("status") or "").strip().lower() in {"blocked", "unreachable"}
        )
        today_cutoff = utc_today
        week_cutoff = utc_today - timedelta(days=6)
        new_users_today = 0
        new_users_week = 0
        referrals_total = 0
        for row in totals_rows:
            first_seen = _parse_timestamp(row.get("first_seen_at"))
            if first_seen and first_seen >= today_cutoff:
                new_users_today += 1
            if first_seen and first_seen >= week_cutoff:
                new_users_week += 1
            if _safe_int(row.get("referred_by")) > 0:
                referrals_total += 1

        recent_response = (
            client.table(config.history_table)
            .select(
                (
                    "id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at,"
                    "frontend_source,feature_used,conversation_id,text_content,media_type,media_url"
                )
            )
            .order("created_at", desc=True)
            .limit(16)
            .execute()
        )
        recent_rows = _response_rows(recent_response)
        users_map = self._load_users_map([_safe_int(item.get("telegram_id")) for item in recent_rows])

        recent_activity: list[dict[str, Any]] = []
        for row in recent_rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            user = users_map.get(telegram_id, {})
            recent_activity.append(
                {
                    "id": row.get("id"),
                    "telegram_id": telegram_id,
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "message_type": row.get("message_type"),
                    "frontend_source": row.get("frontend_source"),
                    "feature_used": row.get("feature_used") or row.get("message_type"),
                    "conversation_id": row.get("conversation_id"),
                    "success": bool(row.get("success")),
                    "created_at": row.get("created_at"),
                    "preview": _truncate_text(
                        row.get("text_content") or row.get("user_message") or row.get("bot_reply"),
                        max_len=130,
                    ),
                    "media_type": row.get("media_type"),
                    "media_url": row.get("media_url"),
                }
            )

        start_day = utc_today - timedelta(days=window_days - 1)
        history_rows = self._fetch_history_since(
            start_day.isoformat(),
            "telegram_id,message_type,created_at",
            max_rows=60000,
        )
        trends = self._build_trends(history_rows, days=window_days)

        return {
            "summary": {
                "total_users": _response_count(total_users_response),
                "unique_users": total_users,
                "total_started_users": total_started_users,
                "active_users": active_users,
                "blocked_users": blocked_users,
                "new_users_today": new_users_today,
                "new_users_week": new_users_week,
                "referrals_total": referrals_total,
                "active_users_today": _response_count(active_users_today_response),
                "total_messages": total_messages,
                "total_images": total_images,
                "total_audio": _response_count(total_audio_response),
            },
            "trends": trends,
            "recent_activity": recent_activity,
            "window_days": window_days,
        }

    def get_messages(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        message_type: str | None = None,
        scope: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        frontend_source: str | None = None,
        feature_used: str | None = None,
    ) -> dict[str, Any]:
        client, config = self._ensure_ready()
        page_limit = _clamp(limit, 1, 100)
        page_offset = max(0, int(offset))
        search_term = str(search or "").strip()
        normalized_message_type = str(message_type or "").strip().lower()
        normalized_scope = str(scope or "all").strip().lower()
        normalized_frontend = str(frontend_source or "").strip().lower()
        normalized_feature = str(feature_used or "").strip().lower()
        normalized_date_from = str(date_from or "").strip()
        normalized_date_to = str(date_to or "").strip()

        query = client.table(config.history_table).select(
            (
                "id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at,"
                "frontend_source,feature_used,conversation_id,text_content,media_type,media_url,"
                "storage_path,mime_type,media_width,media_height,provider_source,media_origin,media_status,media_error_reason"
            ),
            count="exact",
        )
        if normalized_message_type and normalized_message_type != "all":
            query = query.eq("message_type", normalized_message_type)
        if normalized_frontend and normalized_frontend != "all":
            query = query.eq("frontend_source", normalized_frontend)
        if normalized_feature and normalized_feature != "all":
            query = query.eq("feature_used", normalized_feature)
        if normalized_date_from:
            query = query.gte("created_at", normalized_date_from)
        if normalized_date_to:
            query = query.lte("created_at", normalized_date_to)
        if normalized_scope == "private":
            query = query.gte("telegram_id", 1)
        elif normalized_scope == "group":
            query = query.lt("telegram_id", 0)

        if search_term:
            numeric_id = _safe_int(search_term, default=0)
            if search_term.lstrip("-").isdigit() and numeric_id != 0:
                query = query.eq("telegram_id", numeric_id)
            else:
                matching_ids = self._search_user_ids(search_term)
                if not matching_ids:
                    return {
                        "items": [],
                        "total": 0,
                        "limit": page_limit,
                        "offset": page_offset,
                        "has_more": False,
                    }
                query = query.in_("telegram_id", matching_ids)

        response = query.order("created_at", desc=True).range(page_offset, page_offset + page_limit - 1).execute()
        rows = _response_rows(response)
        users_map = self._load_users_map([_safe_int(item.get("telegram_id")) for item in rows])

        items: list[dict[str, Any]] = []
        for row in rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            user = users_map.get(telegram_id, {})
            items.append(
                {
                    "id": row.get("id"),
                    "telegram_id": telegram_id,
                    "scope": "group" if telegram_id < 0 else "private",
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "message_type": row.get("message_type"),
                    "frontend_source": row.get("frontend_source") or "unknown",
                    "feature_used": row.get("feature_used") or row.get("message_type"),
                    "conversation_id": row.get("conversation_id"),
                    "text_content": row.get("text_content") or row.get("user_message"),
                    "user_message": row.get("user_message"),
                    "bot_reply": row.get("bot_reply"),
                    "model_used": row.get("model_used"),
                    "success": bool(row.get("success")),
                    "created_at": row.get("created_at"),
                    "media_type": row.get("media_type"),
                    "media_url": row.get("media_url"),
                    "storage_path": row.get("storage_path"),
                    "preview_ref": _media_preview_ref(row.get("media_url"), row.get("storage_path")),
                    "mime_type": row.get("mime_type"),
                    "media_width": row.get("media_width"),
                    "media_height": row.get("media_height"),
                    "provider_source": row.get("provider_source"),
                    "media_origin": row.get("media_origin"),
                    "media_status": row.get("media_status"),
                    "media_error_reason": row.get("media_error_reason"),
                }
            )

        total = _response_count(response)
        return {
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "has_more": page_offset + len(items) < total,
        }

    def _serialize_user_row(self, row: dict[str, Any], *, active_days: int = 7) -> dict[str, Any]:
        telegram_id = _safe_int(row.get("telegram_id"))
        active_window_days = _clamp(active_days, 1, 60)
        active_cutoff = datetime.now(timezone.utc) - timedelta(days=active_window_days)
        last_seen = _parse_timestamp(row.get("last_seen_at"))
        is_blocked = bool(row.get("is_blocked"))
        status_raw = str(row.get("status") or "").strip().lower()
        status = status_raw or ("blocked" if is_blocked else ("active" if bool(row.get("is_active", True)) else "inactive"))
        is_recently_active = bool(last_seen and last_seen >= active_cutoff)
        return {
            "telegram_id": telegram_id,
            "scope": "group" if telegram_id < 0 else "private",
            "username": row.get("username"),
            "first_name": row.get("first_name"),
            "last_name": row.get("last_name"),
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
            "total_messages": max(0, _safe_int(row.get("total_messages"))),
            "total_images": max(0, _safe_int(row.get("total_images"))),
            "is_active": is_recently_active,
            "has_started": bool(row.get("has_started")),
            "started_at": row.get("started_at"),
            "status": status,
            "is_blocked": is_blocked,
            "blocked_at": row.get("blocked_at"),
            "unreachable_count": max(0, _safe_int(row.get("unreachable_count"))),
            "last_delivery_error": row.get("last_delivery_error"),
            "referral_code": row.get("referral_code"),
            "referred_by": _safe_int(row.get("referred_by")),
            "started_via_referral": row.get("started_via_referral"),
            "last_engagement_sent_at": row.get("last_engagement_sent_at"),
            "engagement_count": max(0, _safe_int(row.get("engagement_count"))),
        }

    def _record_admin_history_event(
        self,
        *,
        telegram_id: int,
        message_type: str,
        feature_used: str,
        user_message: str,
        bot_reply: str,
        success: bool,
        actor_telegram_id: int | None = None,
    ) -> None:
        client, config = self._ensure_ready()
        actor_id = _safe_int(actor_telegram_id)
        actor_suffix = f" (admin:{actor_id})" if actor_id > 0 else ""
        payload = {
            "telegram_id": int(telegram_id),
            "message_type": str(message_type or "admin_action").strip()[:64],
            "user_message": str(user_message or "").strip()[:16000] or None,
            "bot_reply": f"{str(bot_reply or '').strip()[:3000]}{actor_suffix}"[:16000] or None,
            "model_used": None,
            "success": bool(success),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "frontend_source": "admin_dashboard",
            "feature_used": str(feature_used or "admin").strip()[:64] or "admin",
            "conversation_id": f"{int(telegram_id)}:admin_dashboard",
            "text_content": str(user_message or bot_reply or "").strip()[:16000] or None,
        }
        try:
            client.table(config.history_table).insert(payload, returning="minimal").execute()
        except Exception:
            logger.warning(
                "ADMIN HISTORY EVENT INSERT FAILED user=%s type=%s",
                telegram_id,
                message_type,
                exc_info=True,
            )

    def get_users(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        active_days: int = 7,
    ) -> dict[str, Any]:
        client, config = self._ensure_ready()
        page_limit = _clamp(limit, 1, 100)
        page_offset = max(0, int(offset))
        active_window_days = _clamp(active_days, 1, 60)
        search_term = str(search or "").strip()

        query = client.table(config.users_table).select(
            (
                "telegram_id,username,first_name,last_name,first_seen_at,last_seen_at,total_messages,total_images,"
                "has_started,started_at,is_active,status,is_blocked,blocked_at,unreachable_count,last_delivery_error,"
                "referral_code,referred_by,started_via_referral,last_engagement_sent_at,engagement_count"
            ),
            count="exact",
        )
        if search_term:
            numeric_id = _safe_int(search_term, default=0)
            if search_term.lstrip("-").isdigit() and numeric_id != 0:
                query = query.eq("telegram_id", numeric_id)
            else:
                matching_ids = self._search_user_ids(search_term)
                if not matching_ids:
                    return {
                        "items": [],
                        "total": 0,
                        "limit": page_limit,
                        "offset": page_offset,
                        "has_more": False,
                    }
                query = query.in_("telegram_id", matching_ids)

        response = query.order("last_seen_at", desc=True).range(page_offset, page_offset + page_limit - 1).execute()
        rows = _response_rows(response)

        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(self._serialize_user_row(row, active_days=active_window_days))

        total = _response_count(response)
        return {
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "active_window_days": active_window_days,
            "has_more": page_offset + len(items) < total,
        }

    def get_user_profile(self, *, telegram_id: int, activity_limit: int = 25) -> dict[str, Any]:
        client, config = self._ensure_ready()
        user_id = int(telegram_id or 0)
        if user_id == 0:
            raise ValueError("Invalid Telegram ID.")

        user_response = (
            client.table(config.users_table)
            .select(
                (
                    "telegram_id,username,first_name,last_name,first_seen_at,last_seen_at,total_messages,total_images,"
                    "has_started,started_at,is_active,status,is_blocked,blocked_at,unreachable_count,last_delivery_error,"
                    "referral_code,referred_by,started_via_referral,last_engagement_sent_at,engagement_count"
                )
            )
            .eq("telegram_id", user_id)
            .limit(1)
            .execute()
        )
        user_rows = _response_rows(user_response)
        if not user_rows:
            raise LookupError("User not found.")
        user_row = user_rows[0]

        safe_limit = _clamp(activity_limit, 5, 80)
        activity_response = (
            client.table(config.history_table)
            .select(
                (
                    "id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at,frontend_source,"
                    "feature_used,conversation_id,text_content,media_type,media_url,storage_path,mime_type,media_status,media_error_reason"
                )
            )
            .eq("telegram_id", user_id)
            .order("created_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
        activity_rows = _response_rows(activity_response)
        recent_activity: list[dict[str, Any]] = []
        for row in activity_rows:
            recent_activity.append(
                {
                    "id": row.get("id"),
                    "telegram_id": user_id,
                    "message_type": row.get("message_type"),
                    "user_message": row.get("user_message"),
                    "bot_reply": row.get("bot_reply"),
                    "model_used": row.get("model_used"),
                    "success": bool(row.get("success")),
                    "created_at": row.get("created_at"),
                    "frontend_source": row.get("frontend_source") or "unknown",
                    "feature_used": row.get("feature_used") or row.get("message_type"),
                    "conversation_id": row.get("conversation_id"),
                    "text_content": row.get("text_content") or row.get("user_message"),
                    "media_type": row.get("media_type"),
                    "media_url": row.get("media_url"),
                    "storage_path": row.get("storage_path"),
                    "preview_ref": _media_preview_ref(row.get("media_url"), row.get("storage_path")),
                    "mime_type": row.get("mime_type"),
                    "media_status": row.get("media_status"),
                    "media_error_reason": row.get("media_error_reason"),
                }
            )

        blocked_count_response = (
            client.table(config.history_table)
            .select("id", count="exact")
            .eq("telegram_id", user_id)
            .eq("media_status", "blocked")
            .limit(1)
            .execute()
        )
        warnings_count_response = (
            client.table(config.history_table)
            .select("id", count="exact")
            .eq("telegram_id", user_id)
            .eq("message_type", "admin_warn")
            .limit(1)
            .execute()
        )
        return {
            "user": self._serialize_user_row(user_row, active_days=7),
            "summary": {
                "recent_activity_count": len(recent_activity),
                "blocked_prompt_count": _response_count(blocked_count_response),
                "warnings_sent_count": _response_count(warnings_count_response),
            },
            "recent_activity": recent_activity,
        }

    def set_user_access(
        self,
        *,
        telegram_id: int,
        action: str,
        reason: str | None = None,
        actor_telegram_id: int | None = None,
    ) -> dict[str, Any]:
        client, config = self._ensure_ready()
        user_id = int(telegram_id or 0)
        if user_id == 0:
            raise ValueError("Invalid Telegram ID.")
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"block", "unblock", "kick"}:
            raise ValueError("Unsupported user access action.")

        existing_response = (
            client.table(config.users_table)
            .select("telegram_id")
            .eq("telegram_id", user_id)
            .limit(1)
            .execute()
        )
        if not _response_rows(existing_response):
            raise LookupError("User not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        reason_text = str(reason or "").strip()[:300]
        if normalized_action == "unblock":
            update_payload = {
                "is_blocked": False,
                "is_active": True,
                "status": "active",
                "blocked_at": None,
                "last_delivery_error": None,
            }
            action_note = "User access restored by admin."
        elif normalized_action == "kick":
            update_payload = {
                "is_blocked": True,
                "is_active": False,
                "status": "kicked",
                "blocked_at": now_iso,
                "last_delivery_error": reason_text or "Access removed by admin.",
            }
            action_note = "User access removed (kick)."
        else:
            update_payload = {
                "is_blocked": True,
                "is_active": False,
                "status": "blocked",
                "blocked_at": now_iso,
                "last_delivery_error": reason_text or "Blocked by admin.",
            }
            action_note = "User blocked by admin."

        client.table(config.users_table).update(update_payload).eq("telegram_id", user_id).execute()
        updated = self.get_user_profile(telegram_id=user_id, activity_limit=12)
        self._record_admin_history_event(
            telegram_id=user_id,
            message_type="admin_user_control",
            feature_used=f"admin_user_{normalized_action}",
            user_message=f"action={normalized_action} reason={reason_text or '-'}",
            bot_reply=action_note,
            success=True,
            actor_telegram_id=actor_telegram_id,
        )
        return {
            "ok": True,
            "action": normalized_action,
            "reason": reason_text or None,
            "user": updated.get("user"),
        }

    def log_admin_direct_message(
        self,
        *,
        telegram_id: int,
        message: str,
        delivered: bool,
        actor_telegram_id: int | None = None,
        error: str | None = None,
    ) -> None:
        safe_message = str(message or "").strip()[:2000]
        status_note = "Admin direct message delivered." if delivered else f"Admin direct message failed: {str(error or 'unknown').strip()[:240]}"
        self._record_admin_history_event(
            telegram_id=int(telegram_id),
            message_type="admin_direct_message",
            feature_used="admin_direct_message",
            user_message=safe_message,
            bot_reply=status_note,
            success=bool(delivered),
            actor_telegram_id=actor_telegram_id,
        )

    def log_admin_warning(
        self,
        *,
        telegram_id: int,
        warning_text: str,
        delivered: bool,
        actor_telegram_id: int | None = None,
        error: str | None = None,
    ) -> None:
        safe_warning = str(warning_text or "").strip()[:1500]
        status_note = "Admin warning delivered." if delivered else f"Admin warning delivery failed: {str(error or 'unknown').strip()[:240]}"
        self._record_admin_history_event(
            telegram_id=int(telegram_id),
            message_type="admin_warn",
            feature_used="admin_user_warn",
            user_message=safe_warning,
            bot_reply=status_note,
            success=bool(delivered),
            actor_telegram_id=actor_telegram_id,
        )

    def get_moderation_blocks(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any]:
        client, config = self._ensure_ready()
        page_limit = _clamp(limit, 1, 100)
        page_offset = max(0, int(offset))
        search_term = str(search or "").strip()

        query = (
            client.table(config.history_table)
            .select(
                (
                    "id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at,frontend_source,"
                    "feature_used,conversation_id,text_content,media_type,media_status,media_error_reason"
                ),
                count="exact",
            )
            .eq("media_status", "blocked")
        )
        if search_term:
            numeric_id = _safe_int(search_term, default=0)
            if search_term.lstrip("-").isdigit() and numeric_id != 0:
                query = query.eq("telegram_id", numeric_id)
            else:
                matching_ids = self._search_user_ids(search_term)
                if matching_ids:
                    query = query.in_("telegram_id", matching_ids)
                else:
                    query = query.ilike("user_message", f"%{search_term}%")

        response = query.order("created_at", desc=True).range(page_offset, page_offset + page_limit - 1).execute()
        rows = _response_rows(response)
        users_map = self._load_users_map([_safe_int(item.get("telegram_id")) for item in rows])

        items: list[dict[str, Any]] = []
        for row in rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            user = users_map.get(telegram_id, {})
            items.append(
                {
                    "id": row.get("id"),
                    "telegram_id": telegram_id,
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "message_type": row.get("message_type"),
                    "feature_used": row.get("feature_used"),
                    "model_used": row.get("model_used"),
                    "created_at": row.get("created_at"),
                    "prompt": row.get("user_message") or row.get("text_content"),
                    "moderation_reason": row.get("media_error_reason") or row.get("bot_reply") or "blocked",
                    "frontend_source": row.get("frontend_source") or "unknown",
                    "conversation_id": row.get("conversation_id"),
                }
            )

        now_utc = datetime.now(timezone.utc)
        last_24h_response = (
            client.table(config.history_table)
            .select("id", count="exact")
            .eq("media_status", "blocked")
            .gte("created_at", (now_utc - timedelta(days=1)).isoformat())
            .limit(1)
            .execute()
        )
        last_7d_response = (
            client.table(config.history_table)
            .select("id", count="exact")
            .eq("media_status", "blocked")
            .gte("created_at", (now_utc - timedelta(days=7)).isoformat())
            .limit(1)
            .execute()
        )
        total = _response_count(response)
        return {
            "summary": {
                "total_blocked": total,
                "blocked_last_24h": _response_count(last_24h_response),
                "blocked_last_7d": _response_count(last_7d_response),
            },
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "has_more": page_offset + len(items) < total,
        }

    def get_media(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any]:
        client, config = self._ensure_ready()
        page_limit = _clamp(limit, 1, 100)
        page_offset = max(0, int(offset))
        search_term = str(search or "").strip()
        last_7_days_iso = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        filtered_user_ids: list[int] | None = None

        query = client.table(config.history_table).select(
            (
                "id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at,"
                "frontend_source,feature_used,text_content,media_type,media_url,storage_path,mime_type,"
                "media_width,media_height,provider_source,media_origin,media_status,media_error_reason"
            ),
            count="exact",
        ).in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
        if search_term:
            numeric_id = _safe_int(search_term, default=0)
            if search_term.lstrip("-").isdigit() and numeric_id != 0:
                query = query.eq("telegram_id", numeric_id)
                filtered_user_ids = [numeric_id]
            else:
                matching_ids = self._search_user_ids(search_term)
                if not matching_ids:
                    return {
                        "summary": {
                            "total_media": 0,
                            "total_images": 0,
                            "total_videos": 0,
                            "successful_media": 0,
                            "successful_images": 0,
                            "successful_videos": 0,
                            "media_last_7_days": 0,
                            "images_last_7_days": 0,
                            "videos_last_7_days": 0,
                        },
                        "items": [],
                        "total": 0,
                        "limit": page_limit,
                        "offset": page_offset,
                        "has_more": False,
                    }
                filtered_user_ids = matching_ids
                query = query.in_("telegram_id", matching_ids)

        response = query.order("created_at", desc=True).range(page_offset, page_offset + page_limit - 1).execute()
        rows = _response_rows(response)
        users_map = self._load_users_map([_safe_int(item.get("telegram_id")) for item in rows])

        successful_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("success", True)
        )
        recent_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .gte("created_at", last_7_days_iso)
        )
        image_total_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("media_type", "image")
        )
        video_total_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("media_type", "video")
        )
        image_success_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("success", True)
            .eq("media_type", "image")
        )
        video_success_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("success", True)
            .eq("media_type", "video")
        )
        image_recent_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("media_type", "image")
            .gte("created_at", last_7_days_iso)
        )
        video_recent_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(MEDIA_MESSAGE_TYPES))
            .eq("media_type", "video")
            .gte("created_at", last_7_days_iso)
        )
        if filtered_user_ids:
            if len(filtered_user_ids) == 1:
                successful_query = successful_query.eq("telegram_id", filtered_user_ids[0])
                recent_query = recent_query.eq("telegram_id", filtered_user_ids[0])
                image_total_query = image_total_query.eq("telegram_id", filtered_user_ids[0])
                video_total_query = video_total_query.eq("telegram_id", filtered_user_ids[0])
                image_success_query = image_success_query.eq("telegram_id", filtered_user_ids[0])
                video_success_query = video_success_query.eq("telegram_id", filtered_user_ids[0])
                image_recent_query = image_recent_query.eq("telegram_id", filtered_user_ids[0])
                video_recent_query = video_recent_query.eq("telegram_id", filtered_user_ids[0])
            else:
                successful_query = successful_query.in_("telegram_id", filtered_user_ids)
                recent_query = recent_query.in_("telegram_id", filtered_user_ids)
                image_total_query = image_total_query.in_("telegram_id", filtered_user_ids)
                video_total_query = video_total_query.in_("telegram_id", filtered_user_ids)
                image_success_query = image_success_query.in_("telegram_id", filtered_user_ids)
                video_success_query = video_success_query.in_("telegram_id", filtered_user_ids)
                image_recent_query = image_recent_query.in_("telegram_id", filtered_user_ids)
                video_recent_query = video_recent_query.in_("telegram_id", filtered_user_ids)
        successful_response = successful_query.limit(1).execute()
        last_7_days_response = recent_query.limit(1).execute()
        image_total_response = image_total_query.limit(1).execute()
        video_total_response = video_total_query.limit(1).execute()
        image_success_response = image_success_query.limit(1).execute()
        video_success_response = video_success_query.limit(1).execute()
        image_recent_response = image_recent_query.limit(1).execute()
        video_recent_response = video_recent_query.limit(1).execute()

        items: list[dict[str, Any]] = []
        for row in rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            user = users_map.get(telegram_id, {})
            items.append(
                {
                    "id": row.get("id"),
                    "telegram_id": telegram_id,
                    "scope": "group" if telegram_id < 0 else "private",
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "prompt": row.get("user_message"),
                    "result_note": row.get("bot_reply"),
                    "model_used": row.get("model_used"),
                    "success": bool(row.get("success")),
                    "created_at": row.get("created_at"),
                    "message_type": row.get("message_type"),
                    "frontend_source": row.get("frontend_source") or "unknown",
                    "feature_used": row.get("feature_used") or row.get("message_type"),
                    "text_content": row.get("text_content") or row.get("user_message"),
                    "media_type": row.get("media_type"),
                    "media_url": row.get("media_url"),
                    "storage_path": row.get("storage_path"),
                    "preview_ref": _media_preview_ref(row.get("media_url"), row.get("storage_path")),
                    "mime_type": row.get("mime_type"),
                    "media_width": row.get("media_width"),
                    "media_height": row.get("media_height"),
                    "provider_source": row.get("provider_source"),
                    "media_origin": row.get("media_origin"),
                    "media_status": row.get("media_status"),
                    "media_error_reason": row.get("media_error_reason"),
                }
            )

        total = _response_count(response)
        return {
            "summary": {
                "total_media": total,
                "total_images": _response_count(image_total_response),
                "total_videos": _response_count(video_total_response),
                "successful_media": _response_count(successful_response),
                "successful_images": _response_count(image_success_response),
                "successful_videos": _response_count(video_success_response),
                "media_last_7_days": _response_count(last_7_days_response),
                "images_last_7_days": _response_count(image_recent_response),
                "videos_last_7_days": _response_count(video_recent_response),
            },
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "has_more": page_offset + len(items) < total,
        }

    def get_analytics(self, *, days: int = 30, top_limit: int = 10) -> dict[str, Any]:
        window_days = _clamp(days, 7, 180)
        normalized_top_limit = _clamp(top_limit, 3, 30)
        start_day = _start_of_utc_day() - timedelta(days=window_days - 1)
        rows = self._fetch_history_since(
            start_day.isoformat(),
            "telegram_id,message_type,created_at,success,model_used,frontend_source,feature_used",
            max_rows=80000,
        )
        trends = self._build_trends(rows, days=window_days)

        user_counter: Counter[int] = Counter()
        message_type_counter: Counter[str] = Counter()
        model_counter: Counter[str] = Counter()
        frontend_counter: Counter[str] = Counter()
        feature_counter: Counter[str] = Counter()
        for row in rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            if telegram_id != 0:
                user_counter[telegram_id] += 1
            message_type = str(row.get("message_type") or "unknown").strip().lower() or "unknown"
            message_type_counter[message_type] += 1
            model_used = str(row.get("model_used") or "").strip()
            if model_used:
                model_counter[model_used] += 1
            frontend_source = str(row.get("frontend_source") or "unknown").strip().lower() or "unknown"
            frontend_counter[frontend_source] += 1
            feature_used = str(row.get("feature_used") or message_type).strip().lower() or message_type
            feature_counter[feature_used] += 1

        top_user_ids = [user_id for user_id, _ in user_counter.most_common(normalized_top_limit)]
        users_map = self._load_users_map(top_user_ids)
        top_users: list[dict[str, Any]] = []
        for user_id, event_count in user_counter.most_common(normalized_top_limit):
            profile = users_map.get(user_id, {})
            top_users.append(
                {
                    "telegram_id": user_id,
                    "username": profile.get("username"),
                    "first_name": profile.get("first_name"),
                    "last_name": profile.get("last_name"),
                    "events": event_count,
                    "total_messages": max(0, _safe_int(profile.get("total_messages"))),
                    "total_images": max(0, _safe_int(profile.get("total_images"))),
                }
            )

        return {
            "window_days": window_days,
            "trends": trends,
            "message_type_breakdown": dict(message_type_counter.most_common()),
            "frontend_breakdown": dict(frontend_counter.most_common()),
            "feature_breakdown": dict(feature_counter.most_common()),
            "top_models": [{"model": model, "count": count} for model, count in model_counter.most_common(8)],
            "top_users": top_users,
            "total_events": sum(user_counter.values()),
        }

    def get_referrals(self, *, limit: int = 25, offset: int = 0, search: str | None = None) -> dict[str, Any]:
        client, _config = self._ensure_ready()
        page_limit = _clamp(limit, 1, 100)
        page_offset = max(0, int(offset))
        search_term = str(search or "").strip()

        try:
            query = client.table("referrals").select(
                "id,referral_code,inviter_telegram_id,invitee_telegram_id,frontend_source,created_at",
                count="exact",
            )
            if search_term:
                numeric = _safe_int(search_term, default=0)
                if numeric > 0:
                    query = query.or_(f"inviter_telegram_id.eq.{numeric},invitee_telegram_id.eq.{numeric}")
                else:
                    query = query.ilike("referral_code", f"%{search_term.lower()}%")
            response = query.order("created_at", desc=True).range(page_offset, page_offset + page_limit - 1).execute()
            rows = _response_rows(response)
        except Exception:
            logger.warning("Referral table query failed; returning empty payload.", exc_info=True)
            return {
                "summary": {"total_referrals": 0, "unique_inviters": 0, "unique_invitees": 0},
                "items": [],
                "total": 0,
                "limit": page_limit,
                "offset": page_offset,
                "has_more": False,
            }

        all_ids: list[int] = []
        for row in rows:
            all_ids.extend(
                [
                    _safe_int(row.get("inviter_telegram_id")),
                    _safe_int(row.get("invitee_telegram_id")),
                ]
            )
        users_map = self._load_users_map(all_ids)

        inviter_ids = {_safe_int(row.get("inviter_telegram_id")) for row in rows if _safe_int(row.get("inviter_telegram_id")) > 0}
        invitee_ids = {_safe_int(row.get("invitee_telegram_id")) for row in rows if _safe_int(row.get("invitee_telegram_id")) > 0}
        items: list[dict[str, Any]] = []
        for row in rows:
            inviter_id = _safe_int(row.get("inviter_telegram_id"))
            invitee_id = _safe_int(row.get("invitee_telegram_id"))
            inviter = users_map.get(inviter_id, {})
            invitee = users_map.get(invitee_id, {})
            items.append(
                {
                    "id": row.get("id"),
                    "referral_code": row.get("referral_code"),
                    "inviter_telegram_id": inviter_id,
                    "invitee_telegram_id": invitee_id,
                    "frontend_source": row.get("frontend_source") or "unknown",
                    "created_at": row.get("created_at"),
                    "inviter_username": inviter.get("username"),
                    "inviter_first_name": inviter.get("first_name"),
                    "invitee_username": invitee.get("username"),
                    "invitee_first_name": invitee.get("first_name"),
                }
            )

        total = _response_count(response)
        return {
            "summary": {
                "total_referrals": total,
                "unique_inviters": len(inviter_ids),
                "unique_invitees": len(invitee_ids),
            },
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "has_more": page_offset + len(items) < total,
        }

    def get_engagement_config(self) -> dict[str, Any]:
        client, _config = self._ensure_ready()
        defaults = {
            "enabled": bool(self._settings.engagement_enabled),
            "message_template": str(self._settings.engagement_message_template or "").strip(),
            "inactivity_minutes": int(self._settings.engagement_inactivity_minutes),
            "cooldown_minutes": int(self._settings.engagement_cooldown_minutes),
            "batch_size": int(self._settings.engagement_batch_size),
        }
        try:
            response = client.table("admin_config").select("config_key,value_json,updated_at").eq("config_key", "engagement").limit(1).execute()
            rows = _response_rows(response)
        except Exception:
            logger.warning("Engagement config query failed; falling back to defaults.", exc_info=True)
            return {"config": defaults, "updated_at": None}

        if not rows:
            return {"config": defaults, "updated_at": None}

        value_json = rows[0].get("value_json")
        if isinstance(value_json, dict):
            merged = {
                "enabled": bool(value_json.get("enabled", defaults["enabled"])),
                "message_template": str(value_json.get("message_template") or defaults["message_template"])[:400],
                "inactivity_minutes": _clamp(_safe_int(value_json.get("inactivity_minutes"), defaults["inactivity_minutes"]), 30, 10_080),
                "cooldown_minutes": _clamp(_safe_int(value_json.get("cooldown_minutes"), defaults["cooldown_minutes"]), 30, 43_200),
                "batch_size": _clamp(_safe_int(value_json.get("batch_size"), defaults["batch_size"]), 1, 500),
            }
        else:
            merged = defaults
        return {"config": merged, "updated_at": rows[0].get("updated_at")}

    def update_engagement_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        client, _config = self._ensure_ready()
        current = self.get_engagement_config().get("config", {})
        merged = {
            "enabled": bool(payload.get("enabled", current.get("enabled", True))),
            "message_template": str(payload.get("message_template") or current.get("message_template") or self._settings.engagement_message_template)[:400],
            "inactivity_minutes": _clamp(
                _safe_int(payload.get("inactivity_minutes"), _safe_int(current.get("inactivity_minutes"), self._settings.engagement_inactivity_minutes)),
                30,
                10_080,
            ),
            "cooldown_minutes": _clamp(
                _safe_int(payload.get("cooldown_minutes"), _safe_int(current.get("cooldown_minutes"), self._settings.engagement_cooldown_minutes)),
                30,
                43_200,
            ),
            "batch_size": _clamp(
                _safe_int(payload.get("batch_size"), _safe_int(current.get("batch_size"), self._settings.engagement_batch_size)),
                1,
                500,
            ),
        }
        if not str(merged["message_template"]).strip():
            merged["message_template"] = self._settings.engagement_message_template

        response = client.table("admin_config").upsert(
            {
                "config_key": "engagement",
                "value_json": merged,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="config_key",
            returning="representation",
        ).execute()
        rows = _response_rows(response)
        updated_at = rows[0].get("updated_at") if rows else datetime.now(timezone.utc).isoformat()
        return {"config": merged, "updated_at": updated_at}
