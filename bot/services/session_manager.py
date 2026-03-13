from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import json
from pathlib import Path
import re

from bot.models.session import Feature, JoAIMode, UserSession, feature_label


@dataclass(frozen=True)
class TransitionResult:
    previous: Feature
    current: Feature
    notice: str | None


class SessionManager:
    def __init__(self, known_users_path: Path | None = None) -> None:
        self._sessions: dict[int, UserSession] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._known_users_path = known_users_path
        self._known_users: set[int] = set()
        self._load_known_users()

    @property
    def known_user_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._known_users))

    def get_session(self, user_id: int) -> UserSession:
        self.remember_user(user_id)
        session = self._sessions.get(user_id)
        if session is None:
            session = UserSession(user_id=user_id)
            self._sessions[user_id] = session
        return session

    def get_active_feature(self, user_id: int) -> Feature:
        return self.get_session(user_id).active_feature

    @asynccontextmanager
    async def lock(self, user_id: int):
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock

        async with lock:
            session = self.get_session(user_id)
            yield session
            session.last_updated = datetime.now(timezone.utc)

    async def switch_feature(self, user_id: int, new_feature: Feature) -> TransitionResult:
        async with self.lock(user_id) as session:
            previous = session.active_feature
            if previous != new_feature:
                self._clear_all_feature_state(session)
                session.active_feature = new_feature

            return TransitionResult(previous=previous, current=session.active_feature, notice=None)

    async def reset_to_menu(self, user_id: int) -> TransitionResult:
        return await self.switch_feature(user_id, Feature.NONE)

    def remember_user(self, user_id: int) -> None:
        if user_id in self._known_users:
            return
        self._known_users.add(user_id)
        self._save_known_users()

    def _clear_all_feature_state(self, session: UserSession) -> None:
        session.jo_ai_mode = JoAIMode.MENU
        session.jo_ai_prompt_type = None
        session.jo_ai_image_ratio = None
        session.jo_ai_kimi_waiting_image = False
        session.jo_ai_last_image_file_id = None
        session.jo_ai_last_image_prompt = None
        session.jo_ai_code_waiting_file = False
        session.jo_ai_code_file_name = None
        session.jo_ai_code_file_content = None
        session.jo_ai_tts_language = None
        session.jo_ai_tts_voice = None
        session.jo_ai_tts_style = None
        session.jo_ai_tts_emotion = None
        session.jo_ai_chat_history.clear()

    def _transition_notice(self, previous: Feature, new_feature: Feature) -> str:
        if new_feature == Feature.NONE:
            if previous == Feature.AI_TOOLS_MENU:
                return "Returning to main menu."
            if previous == Feature.JO_AI:
                return "Returning to main menu."
            return "Returning to main menu."

        if previous == Feature.NONE and new_feature == Feature.AI_TOOLS_MENU:
            return "Opening AI tools."
        if previous == Feature.NONE and new_feature == Feature.JO_AI:
            return "Opening JO AI."
        if previous == Feature.JO_AI and new_feature == Feature.AI_TOOLS_MENU:
            return "Opening AI tools."
        if previous != Feature.JO_AI and new_feature == Feature.JO_AI:
            return "Opening JO AI."

        return f"Opening {feature_label(new_feature)}."

    def _load_known_users(self) -> None:
        if self._known_users_path is None:
            return

        if self._known_users_path.exists():
            try:
                payload = json.loads(self._known_users_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = []

            if isinstance(payload, list):
                for value in payload:
                    if isinstance(value, int) and value > 0:
                        self._known_users.add(value)
                    elif isinstance(value, str) and value.isdigit():
                        self._known_users.add(int(value))

        if not self._known_users:
            self._load_known_users_from_log()

    def _save_known_users(self) -> None:
        if self._known_users_path is None:
            return

        try:
            self._known_users_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(sorted(self._known_users), indent=2)
            self._known_users_path.write_text(payload, encoding="utf-8")
        except OSError:
            return

    def _load_known_users_from_log(self) -> None:
        if self._known_users_path is None:
            return

        project_root = self._known_users_path.parents[2] if len(self._known_users_path.parents) >= 3 else None
        if project_root is None:
            return

        log_path = project_root / "logs" / "bot.log"
        if not log_path.exists():
            return

        try:
            content = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return

        for user_id in re.findall(r"User action: id=(\d+)", content):
            self._known_users.add(int(user_id))

        if self._known_users:
            self._save_known_users()
