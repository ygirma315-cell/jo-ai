from __future__ import annotations

from datetime import datetime
import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import main
from bot.config import load_settings


class TestRenderStartupConfig(unittest.TestCase):
    def test_missing_bot_token_is_warning_not_startup_error(self) -> None:
        env = {
            "BOT_TOKEN": " ",
            "TELEGRAM_BOT_TOKEN": " ",
            "NVIDIA_API_KEY": "test-api-key",
            "KEEPALIVE_SELF_PING_ENABLED": "false",
        }

        with patch.dict(os.environ, env, clear=True), patch("bot.config.load_dotenv", lambda *_args, **_kwargs: None):
            settings = load_settings()

        self.assertEqual(settings.bot_token, "")
        self.assertEqual(settings.bot_token_env_var, "")
        self.assertEqual(settings.validation_errors, ())
        self.assertTrue(
            any("BOT_TOKEN is missing" in warning for warning in settings.validation_warnings),
            settings.validation_warnings,
        )

    def test_render_external_url_wins_over_stale_public_base_url(self) -> None:
        env = {
            "BOT_TOKEN": "123456:test-token",
            "NVIDIA_API_KEY": "test-api-key",
            "PUBLIC_BASE_URL": "https://jo-ai.onrender.com",
            "RENDER_EXTERNAL_URL": "https://jo-ai-fowf.onrender.com",
        }

        with patch.dict(os.environ, env, clear=True), patch("bot.config.load_dotenv", lambda *_args, **_kwargs: None):
            settings = load_settings()

        self.assertEqual(settings.public_base_url, "https://jo-ai-fowf.onrender.com")
        self.assertEqual(settings.telegram_webhook_url, "https://jo-ai-fowf.onrender.com/telegram/webhook")
        self.assertTrue(
            any("PUBLIC_BASE_URL differs" in warning for warning in settings.validation_warnings),
            settings.validation_warnings,
        )

    def test_render_external_url_wins_over_stale_webhook_override(self) -> None:
        env = {
            "BOT_TOKEN": "123456:test-token",
            "NVIDIA_API_KEY": "test-api-key",
            "RENDER_EXTERNAL_URL": "https://jo-ai-fowf.onrender.com",
            "TELEGRAM_WEBHOOK_URL": "https://jo-ai.onrender.com/telegram/webhook",
        }

        with patch.dict(os.environ, env, clear=True), patch("bot.config.load_dotenv", lambda *_args, **_kwargs: None):
            settings = load_settings()

        self.assertEqual(settings.telegram_webhook_url, "https://jo-ai-fowf.onrender.com/telegram/webhook")
        self.assertTrue(
            any("TELEGRAM_WEBHOOK_URL differs" in warning for warning in settings.validation_warnings),
            settings.validation_warnings,
        )

    def test_keepalive_sleep_window_covers_midnight_to_six_am(self) -> None:
        env = {
            "KEEPALIVE_SLEEP_WINDOW_ENABLED": "true",
            "KEEPALIVE_SLEEP_TIMEZONE": "Africa/Nairobi",
            "KEEPALIVE_SLEEP_START_HOUR": "0",
            "KEEPALIVE_SLEEP_END_HOUR": "6",
        }
        tz = ZoneInfo("Africa/Nairobi")

        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(main._is_keepalive_sleep_window(datetime(2026, 6, 17, 0, 30, tzinfo=tz)))
            self.assertTrue(main._is_keepalive_sleep_window(datetime(2026, 6, 17, 5, 59, tzinfo=tz)))
            self.assertFalse(main._is_keepalive_sleep_window(datetime(2026, 6, 17, 6, 0, tzinfo=tz)))
            self.assertFalse(main._is_keepalive_sleep_window(datetime(2026, 6, 17, 23, 0, tzinfo=tz)))


if __name__ == "__main__":
    unittest.main()
