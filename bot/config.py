from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    known_users_path: Path
    log_level: str
    nvidia_api_key: str | None
    nvidia_chat_model: str
    deepseek_api_key: str | None
    deepseek_model: str
    kimi_api_key: str | None
    kimi_model: str
    miniapp_url: str | None
    miniapp_api_base: str | None


def load_settings() -> Settings:
    load_dotenv()
    root_dir = Path(__file__).resolve().parent.parent

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("Missing BOT_TOKEN. Set it in .env before running the bot.")

    known_users_raw = os.getenv("KNOWN_USERS_PATH", "bot/data/known_users.json").strip()
    known_users_path = Path(known_users_raw)
    if not known_users_path.is_absolute():
        known_users_path = (root_dir / known_users_path).resolve()

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    nvidia_api_key = os.getenv("NVIDIA_API_KEY", "").strip() or None
    if not nvidia_api_key:
        nvidia_api_key = os.getenv("JOAI_API_KEY", "").strip() or None
    nvidia_chat_model = os.getenv("NVIDIA_CHAT_MODEL", "meta/llama-3.1-8b-instruct").strip()
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or None
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-ai/deepseek-v3.2").strip()
    kimi_api_key = os.getenv("KIMI_API_KEY", "").strip() or None
    kimi_model = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5").strip()
    miniapp_url = os.getenv("MINIAPP_URL", "").strip() or None
    miniapp_api_base = os.getenv("MINIAPP_API_BASE", "").strip() or None

    return Settings(
        bot_token=bot_token,
        known_users_path=known_users_path,
        log_level=log_level,
        nvidia_api_key=nvidia_api_key,
        nvidia_chat_model=nvidia_chat_model,
        deepseek_api_key=deepseek_api_key,
        deepseek_model=deepseek_model,
        kimi_api_key=kimi_api_key,
        kimi_model=kimi_model,
        miniapp_url=miniapp_url,
        miniapp_api_base=miniapp_api_base,
    )
