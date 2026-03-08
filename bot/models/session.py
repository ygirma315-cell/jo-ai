from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Feature(str, Enum):
    NONE = "none"
    AI_TOOLS_MENU = "ai_tools_menu"
    UTILITIES_MENU = "utilities_menu"
    CALCULATOR = "calculator"
    GAMES_MENU = "games_menu"
    TIC_TAC_TOE = "tic_tac_toe"
    GUESS_NUMBER = "guess_number"
    JO_AI = "jo_ai"


GAME_FEATURES = {Feature.TIC_TAC_TOE, Feature.GUESS_NUMBER}


class JoAIMode(str, Enum):
    MENU = "menu"
    CHAT = "chat"
    CODE = "code"
    RESEARCH = "research"
    DEEP_ANALYSIS = "deep_analysis"
    PROMPT = "prompt"
    IMAGE = "image"
    KIMI_IMAGE_DESCRIBER = "kimi_image_describer"
    TEXT_TO_SPEECH = "text_to_speech"


def is_game_feature(feature: Feature) -> bool:
    return feature in GAME_FEATURES


def feature_label(feature: Feature) -> str:
    labels = {
        Feature.NONE: "Main menu",
        Feature.AI_TOOLS_MENU: "AI tools",
        Feature.UTILITIES_MENU: "utilities",
        Feature.CALCULATOR: "calculator",
        Feature.GAMES_MENU: "games",
        Feature.TIC_TAC_TOE: "tic-tac-toe",
        Feature.GUESS_NUMBER: "guess the number",
        Feature.JO_AI: "Jo AI",
    }
    return labels.get(feature, "feature")


@dataclass
class TicTacToeState:
    game_id: str
    board: list[str] = field(default_factory=lambda: [" "] * 9)
    finished: bool = False


@dataclass
class GuessNumberState:
    game_id: str
    target: int
    min_value: int = 1
    max_value: int = 100
    attempts: int = 0
    finished: bool = False


@dataclass
class UserSession:
    user_id: int
    active_feature: Feature = Feature.NONE
    calculator_active: bool = False
    tic_tac_toe: TicTacToeState | None = None
    guess_number: GuessNumberState | None = None
    jo_ai_mode: JoAIMode = JoAIMode.MENU
    jo_ai_prompt_type: str | None = None
    jo_ai_image_type: str | None = None
    jo_ai_image_ratio: str | None = None
    jo_ai_kimi_waiting_image: bool = False
    jo_ai_last_image_file_id: str | None = None
    jo_ai_code_waiting_file: bool = False
    jo_ai_code_file_name: str | None = None
    jo_ai_code_file_content: str | None = None
    jo_ai_tts_language: str | None = None
    jo_ai_tts_voice: str | None = None
    jo_ai_tts_emotion: str | None = None
    jo_ai_chat_history: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=20))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
