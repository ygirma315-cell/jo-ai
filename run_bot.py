from __future__ import annotations

import asyncio
import sys

from bot.app import run_bot
from version import VERSION


if __name__ == "__main__":
    print(f"🚀 BOT STARTED — VERSION {VERSION}", flush=True)
    print(f"[RENDER] PROCESS=bot-worker ENTRYPOINT=run_bot.py VERSION={VERSION}", flush=True)
    try:
        asyncio.run(run_bot())
    except RuntimeError as exc:
        message = str(exc)
        if "Missing required Telegram token" in message:
            raise SystemExit(f"FATAL: {message}") from None
        raise
    except KeyboardInterrupt:
        sys.exit(0)
