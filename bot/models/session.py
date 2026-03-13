from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Feature(str, Enum):
    NONE = "none"
    AI_TOOLS_MENU = "ai_tools_menu"
    JO_AI = "jo_ai"


class JoAIMode(str, Enum):
    MENU = "menu"
    CHAT = "chat"
    GEMINI = "gemini"
    CODE = "code"
    RESEARCH = "research"
    DEEP_ANALYSIS = "deep_analysis"
    PROMPT = "prompt"
    IMAGE = "image"
    KIMI_IMAGE_DESCRIBER = "kimi_image_describer"
    TEXT_TO_SPEECH = "text_to_speech"


def feature_label(feature: Feature) -> str:
    labels = {
        Feature.NONE: "Main menu",
        Feature.AI_TOOLS_MENU: "AI tools",
        Feature.JO_AI: "JO AI",
    }
    return labels.get(feature, "feature")


@dataclass
class UserSession:
    user_id: int
    active_feature: Feature = Feature.NONE
    jo_ai_mode: JoAIMode = JoAIMode.MENU
    jo_ai_prompt_type: str | None = None
    jo_ai_image_ratio: str | None = None
    jo_ai_kimi_waiting_image: bool = False
    jo_ai_last_image_file_id: str | None = None
    jo_ai_last_image_prompt: str | None = None
    jo_ai_code_waiting_file: bool = False
    jo_ai_code_file_name: str | None = None
    jo_ai_code_file_content: str | None = None
    jo_ai_tts_language: str | None = None
    jo_ai_tts_voice: str | None = None
    jo_ai_tts_style: str | None = None
    jo_ai_tts_emotion: str | None = None
    jo_ai_chat_history: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=20))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
