from __future__ import annotations

import asyncio
import sys

from bot.app import run_bot


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except RuntimeError as exc:
        message = str(exc)
        if "Missing required Telegram token" in message:
            raise SystemExit(f"FATAL: {message}") from None
        raise
    except KeyboardInterrupt:
        sys.exit(0)
