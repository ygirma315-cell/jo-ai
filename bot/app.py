from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
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

logger = logging.getLogger(__name__)

NETWORK_RETRY_BASE_SECONDS = 2
NETWORK_RETRY_MAX_SECONDS = 30
RESTART_BROADCAST_TEXT = (
    "Bot was restarted with updates.\n"
    "Please send /restart to refresh your session."
)


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


async def _configure_chat_menu_button(bot: Bot, miniapp_url: str | None, miniapp_api_base: str | None) -> None:
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
    except Exception:
        logger.warning("Failed to configure Telegram chat menu button.", exc_info=True)


async def _notify_known_users_on_restart(bot: Bot, session_manager: SessionManager) -> None:
    sent_count = 0
    failed_count = 0
    for user_id in session_manager.known_user_ids:
        try:
            await bot.send_message(chat_id=user_id, text=RESTART_BROADCAST_TEXT)
            sent_count += 1
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


async def _start_polling_with_retries(dispatcher: Dispatcher, bot: Bot) -> None:
    attempt = 0
    dropped_pending_updates = False
    allowed_updates = dispatcher.resolve_used_update_types()

    while True:
        try:
            attempt += 1
            me = await bot.get_me()
            logger.info("Connected to Telegram as @%s (id=%s).", me.username or "unknown", me.id)
            if not dropped_pending_updates:
                await bot.delete_webhook(drop_pending_updates=True)
                dropped_pending_updates = True
                logger.info("Dropped pending Telegram updates on startup to avoid stale sessions.")
            logger.info("POLLING STARTED | allowed_updates=%s", ",".join(allowed_updates))
            await dispatcher.start_polling(bot, allowed_updates=allowed_updates)
            return
        except asyncio.CancelledError:
            raise
        except (TelegramNetworkError, ClientConnectorError, asyncio.TimeoutError) as exc:
            delay = min(NETWORK_RETRY_BASE_SECONDS * (2 ** (attempt - 1)), NETWORK_RETRY_MAX_SECONDS)
            logger.warning(
                "Telegram network error (%s): %s. Retrying in %s seconds (attempt %s).",
                type(exc).__name__,
                exc,
                delay,
                attempt,
            )
            await asyncio.sleep(delay)
        except Exception:
            logger.exception("Bot stopped due to unexpected error.")
            raise


async def run_bot() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    logger.info("TOKEN LOADED | env_var=%s", settings.bot_token_env_var)
    logger.info("BOT STARTED")

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

    try:
        await _configure_chat_menu_button(bot, settings.miniapp_url, settings.miniapp_api_base)
        await _notify_known_users_on_restart(bot, session_manager)
        await _start_polling_with_retries(dispatcher, bot)
    finally:
        await bot.session.close()
