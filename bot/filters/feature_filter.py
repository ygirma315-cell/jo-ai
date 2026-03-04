from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.models.session import Feature
from bot.services.session_manager import SessionManager


class ActiveFeatureFilter(BaseFilter):
    def __init__(self, feature: Feature) -> None:
        self.feature = feature

    async def __call__(self, event: Message | CallbackQuery, session_manager: SessionManager) -> bool:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            return session_manager.get_active_feature(event.from_user.id) == self.feature
        return False
