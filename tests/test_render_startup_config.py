from __future__ import annotations

import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
