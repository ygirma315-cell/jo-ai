from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging


def setup_logging(level: str = "INFO") -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        logs_dir / "bot.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        handlers=[console_handler, file_handler],
        force=True,
    )

