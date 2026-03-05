from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, Update, WebAppInfo
from aiohttp import ClientConnectorError

from bot.config import load_settings
from bot.error_handler import register_error_handler
from bot.handlers.calculator import router as calculator_router
from bot.handlers.common import router as common_router
from bot.handlers.fallback import router as fallback_router
from bot.handlers.games import router as games_router
from bot.handlers.jo_ai import router as jo_ai_router
from bot.logging_config import setup_logging
from bot.middlewares.logging import UserActionLoggingMiddleware
from bot.services.ai_service import ChatService, ImageGenerationService, VideoGenerationService
from bot.services.calculator_service import CalculatorService
from bot.services.guess_number_service import GuessNumberService
from bot.services.session_manager import SessionManager
from bot.services.tictactoe_service import TicTacToeService
from bot.telegram_formatting import run_markdown_sanity_checks
from version import VERSION

logger = logging.getLogger(__name__)

RESTART_BROADCAST_TEXT = (
    "Bot was restarted with updates.\n"
    "Please send /restart to refresh your session."
)
TELEGRAM_STARTUP_RETRY_DELAYS_SECONDS = (5, 15, 30, 60)
TELEGRAM_STARTUP_MAX_ATTEMPTS = len(TELEGRAM_STARTUP_RETRY_DELAYS_SECONDS)


@dataclass(slots=True)
class BotRuntime:
    bot: Bot
    dispatcher: Dispatcher
    token_env_var: str
    session_manager: SessionManager
    miniapp_url: str | None
    miniapp_api_base: str | None


def _build_miniapp_url(miniapp_url: str | None, api_base: str | None) -> str | None:
    if not miniapp_url:
        return None
    if not api_base:
        return miniapp_url

    parsed = urlparse(miniapp_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["api_base"] = api_base
    rebuilt = parsed._replace(query=urlencode(query))
    return urlunparse(rebuilt)


def _env_flag_enabled(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


async def _configure_chat_menu_button(bot: Bot, miniapp_url: str | None, miniapp_api_base: str | None) -> bool:
    try:
        resolved_miniapp_url = _build_miniapp_url(miniapp_url, miniapp_api_base)
        if resolved_miniapp_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=resolved_miniapp_url))
            )
            logger.info("Configured Telegram chat menu button as WebApp 'Open'.")
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            logger.info("Configured Telegram chat menu button as command list.")
        return True
    except (TelegramNetworkError, ClientConnectorError, asyncio.TimeoutError) as exc:
        logger.warning("Telegram network unavailable while setting chat menu button: %s", exc)
        return False
    except Exception:
        logger.warning("Failed to configure Telegram chat menu button.", exc_info=True)
        return True


async def _notify_known_users_on_restart(bot: Bot, session_manager: SessionManager) -> bool:
    sent_count = 0
    failed_count = 0
    for user_id in session_manager.known_user_ids:
        try:
            await bot.send_message(chat_id=user_id, text=RESTART_BROADCAST_TEXT)
            sent_count += 1
        except (TelegramNetworkError, ClientConnectorError, asyncio.TimeoutError) as exc:
            logger.warning("Telegram network unavailable while sending restart notifications: %s", exc)
            return False
        except (TelegramForbiddenError, TelegramBadRequest):
            failed_count += 1
        except Exception:
            failed_count += 1
            logger.warning("Could not send restart notification to user id=%s.", user_id, exc_info=True)

    if sent_count or failed_count:
        logger.info(
            "Restart notification completed. sent=%s failed=%s total=%s",
            sent_count,
            failed_count,
            sent_count + failed_count,
        )
    return True


async def _run_telegram_startup_tasks_once(runtime: BotRuntime) -> bool:
    menu_ready = await _configure_chat_menu_button(runtime.bot, runtime.miniapp_url, runtime.miniapp_api_base)
    notifications_sent = await _notify_known_users_on_restart(runtime.bot, runtime.session_manager)
    return menu_ready and notifications_sent


async def run_telegram_startup_tasks_with_backoff(runtime: BotRuntime) -> None:
    if _env_flag_enabled("DISABLE_TELEGRAM_STARTUP_TASKS"):
        logger.info("Telegram startup tasks skipped (DISABLE_TELEGRAM_STARTUP_TASKS=1).")
        return

    max_attempts = TELEGRAM_STARTUP_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            completed = await _run_telegram_startup_tasks_once(runtime)
        except asyncio.CancelledError:
            raise
        except Exception:
            completed = False
            logger.warning("Unexpected error while running Telegram startup tasks.", exc_info=True)

        if completed:
            logger.info("Telegram startup tasks completed on attempt %s.", attempt)
            return

        if attempt >= max_attempts:
            break

        delay_seconds = TELEGRAM_STARTUP_RETRY_DELAYS_SECONDS[min(attempt - 1, len(TELEGRAM_STARTUP_RETRY_DELAYS_SECONDS) - 1)]
        logger.warning(
            "Telegram startup tasks attempt %s/%s failed. Retrying in %s seconds.",
            attempt,
            max_attempts,
            delay_seconds,
        )
        await asyncio.sleep(delay_seconds)

    logger.warning("Telegram startup tasks failed after %s attempts; will retry later.", max_attempts)


def start_telegram_startup_tasks(runtime: BotRuntime) -> asyncio.Task[None]:
    return asyncio.create_task(run_telegram_startup_tasks_with_backoff(runtime), name="telegram-startup-tasks")


async def create_bot_runtime() -> BotRuntime:
    settings = load_settings()
    setup_logging(settings.log_level)
    run_markdown_sanity_checks()
    logger.info("TOKEN LOADED | env_var=%s", settings.bot_token_env_var)
    logger.info("🤖 BOT INIT — VERSION %s", VERSION)
    process_role = os.getenv("PROCESS_ROLE", "bot-worker").strip() or "bot-worker"
    logger.info("[RENDER] PROCESS=%s ENTRYPOINT=main.py VERSION=%s", process_role, VERSION)

    # aiogram expects timeout as number of seconds, not aiohttp.ClientTimeout object.
    session = AiohttpSession(timeout=30)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dispatcher = Dispatcher()

    session_manager = SessionManager(known_users_path=settings.known_users_path)
    dispatcher["session_manager"] = session_manager
    dispatcher["calculator_service"] = CalculatorService()
    dispatcher["tictactoe_service"] = TicTacToeService()
    dispatcher["guess_number_service"] = GuessNumberService()
    dispatcher["chat_service"] = ChatService(api_key=settings.nvidia_api_key, model=settings.nvidia_chat_model)
    dispatcher["image_generation_service"] = ImageGenerationService(api_key=settings.nvidia_api_key)
    dispatcher["video_generation_service"] = VideoGenerationService(api_key=settings.nvidia_api_key)
    dispatcher["deepseek_api_key"] = settings.deepseek_api_key
    dispatcher["deepseek_model"] = settings.deepseek_model
    dispatcher["kimi_api_key"] = settings.kimi_api_key
    dispatcher["kimi_model"] = settings.kimi_model
    dispatcher["miniapp_url"] = settings.miniapp_url

    dispatcher.message.middleware(UserActionLoggingMiddleware())
    dispatcher.callback_query.middleware(UserActionLoggingMiddleware())

    dispatcher.include_router(common_router)
    dispatcher.include_router(calculator_router)
    dispatcher.include_router(games_router)
    dispatcher.include_router(jo_ai_router)
    dispatcher.include_router(fallback_router)
    register_error_handler(dispatcher)

    logger.info("Webhook runtime initialized (startup tasks scheduled separately).")
    return BotRuntime(
        bot=bot,
        dispatcher=dispatcher,
        token_env_var=settings.bot_token_env_var,
        session_manager=session_manager,
        miniapp_url=settings.miniapp_url,
        miniapp_api_base=settings.miniapp_api_base,
    )


async def process_telegram_update(runtime: BotRuntime, update: Update) -> None:
    await runtime.dispatcher.feed_update(runtime.bot, update)


async def close_bot_runtime(runtime: BotRuntime) -> None:
    await runtime.bot.session.close()


async def run_bot() -> None:
    raise RuntimeError(
        "Polling mode is disabled. Run `uvicorn main:app --host 0.0.0.0 --port $PORT` and use webhook mode."
    )
