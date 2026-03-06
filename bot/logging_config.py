from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import os


def setup_logging(level: str = "INFO") -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [console_handler]

    log_to_file = os.getenv("LOG_TO_FILE", "").strip().lower() in {"1", "true", "yes", "on"}
    running_on_render = bool(os.getenv("RENDER")) or bool(os.getenv("RENDER_EXTERNAL_URL"))
    if log_to_file and not running_on_render:
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            logs_dir / "bot.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        handlers=handlers,
        force=True,
    )
