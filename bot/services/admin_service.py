from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from supabase import Client, create_client

from bot.config import Settings, load_settings
from bot.services.supabase_client import SupabaseConfig, build_supabase_config

logger = logging.getLogger(__name__)
IMAGE_MESSAGE_TYPE = "image"
AUDIO_MESSAGE_TYPES = frozenset({"tts", "voice", "audio"})


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

    def _fetch_all_user_totals(self, max_rows: int = 50000) -> list[dict[str, Any]]:
        client, config = self._ensure_ready()
        page_size = 1000
        offset = 0
        rows: list[dict[str, Any]] = []

        while offset < max_rows:
            response = (
                client.table(config.users_table)
                .select("telegram_id,total_messages,total_images")
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
            "telegram_id,username,first_name,last_name,total_messages,total_images,last_seen_at,first_seen_at"
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
            if message_type == IMAGE_MESSAGE_TYPE:
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

        total_users_response = (
            client.table(config.users_table).select("telegram_id", count="exact").limit(1).execute()
        )
        active_users_today_response = (
            client.table(config.users_table)
            .select("telegram_id", count="exact")
            .gte("last_seen_at", today_iso)
            .limit(1)
            .execute()
        )
        total_audio_response = (
            client.table(config.history_table)
            .select("id", count="exact")
            .in_("message_type", sorted(AUDIO_MESSAGE_TYPES))
            .limit(1)
            .execute()
        )

        totals_rows = self._fetch_all_user_totals()
        total_messages = sum(max(0, _safe_int(item.get("total_messages"))) for item in totals_rows)
        total_images = sum(max(0, _safe_int(item.get("total_images"))) for item in totals_rows)

        recent_response = (
            client.table(config.history_table)
            .select("id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at")
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
                    "success": bool(row.get("success")),
                    "created_at": row.get("created_at"),
                    "preview": _truncate_text(row.get("user_message") or row.get("bot_reply"), max_len=130),
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
    ) -> dict[str, Any]:
        client, config = self._ensure_ready()
        page_limit = _clamp(limit, 1, 100)
        page_offset = max(0, int(offset))
        search_term = str(search or "").strip()
        normalized_message_type = str(message_type or "").strip().lower()
        normalized_scope = str(scope or "all").strip().lower()

        query = client.table(config.history_table).select(
            "id,telegram_id,message_type,user_message,bot_reply,model_used,success,created_at",
            count="exact",
        )
        if normalized_message_type and normalized_message_type != "all":
            query = query.eq("message_type", normalized_message_type)
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
                    "user_message": row.get("user_message"),
                    "bot_reply": row.get("bot_reply"),
                    "model_used": row.get("model_used"),
                    "success": bool(row.get("success")),
                    "created_at": row.get("created_at"),
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
            "telegram_id,username,first_name,last_name,first_seen_at,last_seen_at,total_messages,total_images",
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
        active_cutoff = datetime.now(timezone.utc) - timedelta(days=active_window_days)

        items: list[dict[str, Any]] = []
        for row in rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            last_seen = _parse_timestamp(row.get("last_seen_at"))
            items.append(
                {
                    "telegram_id": telegram_id,
                    "scope": "group" if telegram_id < 0 else "private",
                    "username": row.get("username"),
                    "first_name": row.get("first_name"),
                    "last_name": row.get("last_name"),
                    "first_seen_at": row.get("first_seen_at"),
                    "last_seen_at": row.get("last_seen_at"),
                    "total_messages": max(0, _safe_int(row.get("total_messages"))),
                    "total_images": max(0, _safe_int(row.get("total_images"))),
                    "is_active": bool(last_seen and last_seen >= active_cutoff),
                }
            )

        total = _response_count(response)
        return {
            "items": items,
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
            "active_window_days": active_window_days,
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
            "id,telegram_id,user_message,bot_reply,model_used,success,created_at",
            count="exact",
        ).eq("message_type", IMAGE_MESSAGE_TYPE)
        if search_term:
            numeric_id = _safe_int(search_term, default=0)
            if search_term.lstrip("-").isdigit() and numeric_id != 0:
                query = query.eq("telegram_id", numeric_id)
                filtered_user_ids = [numeric_id]
            else:
                matching_ids = self._search_user_ids(search_term)
                if not matching_ids:
                    return {
                        "summary": {"total_images": 0, "successful_images": 0, "images_last_7_days": 0},
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
            .eq("message_type", IMAGE_MESSAGE_TYPE)
            .eq("success", True)
        )
        recent_query = (
            client.table(config.history_table)
            .select("id", count="exact")
            .eq("message_type", IMAGE_MESSAGE_TYPE)
            .gte("created_at", last_7_days_iso)
        )
        if filtered_user_ids:
            if len(filtered_user_ids) == 1:
                successful_query = successful_query.eq("telegram_id", filtered_user_ids[0])
                recent_query = recent_query.eq("telegram_id", filtered_user_ids[0])
            else:
                successful_query = successful_query.in_("telegram_id", filtered_user_ids)
                recent_query = recent_query.in_("telegram_id", filtered_user_ids)
        successful_response = successful_query.limit(1).execute()
        last_7_days_response = recent_query.limit(1).execute()

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
                }
            )

        total = _response_count(response)
        return {
            "summary": {
                "total_images": total,
                "successful_images": _response_count(successful_response),
                "images_last_7_days": _response_count(last_7_days_response),
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
            "telegram_id,message_type,created_at,success,model_used",
            max_rows=80000,
        )
        trends = self._build_trends(rows, days=window_days)

        user_counter: Counter[int] = Counter()
        message_type_counter: Counter[str] = Counter()
        model_counter: Counter[str] = Counter()
        for row in rows:
            telegram_id = _safe_int(row.get("telegram_id"))
            if telegram_id != 0:
                user_counter[telegram_id] += 1
            message_type = str(row.get("message_type") or "unknown").strip().lower() or "unknown"
            message_type_counter[message_type] += 1
            model_used = str(row.get("model_used") or "").strip()
            if model_used:
                model_counter[model_used] += 1

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
            "top_models": [{"model": model, "count": count} for model, count in model_counter.most_common(8)],
            "top_users": top_users,
            "total_events": sum(user_counter.values()),
        }
