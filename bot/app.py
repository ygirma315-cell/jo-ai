from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, Update, WebAppInfo

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
from version import VERSION

logger = logging.getLogger(__name__)

RESTART_BROADCAST_TEXT = (
    "Bot was restarted with updates.\n"
    "Please send /restart to refresh your session."
)


@dataclass(slots=True)
class BotRuntime:
    bot: Bot
    dispatcher: Dispatcher
    token_env_var: str


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


async def create_bot_runtime() -> BotRuntime:
    settings = load_settings()
    setup_logging(settings.log_level)
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

    await _configure_chat_menu_button(bot, settings.miniapp_url, settings.miniapp_api_base)
    await _notify_known_users_on_restart(bot, session_manager)

    me = await bot.get_me()
    logger.info("Webhook runtime ready for @%s (id=%s).", me.username or "unknown", me.id)
    return BotRuntime(bot=bot, dispatcher=dispatcher, token_env_var=settings.bot_token_env_var)


async def process_telegram_update(runtime: BotRuntime, update: Update) -> None:
    await runtime.dispatcher.feed_update(runtime.bot, update)


async def close_bot_runtime(runtime: BotRuntime) -> None:
    await runtime.bot.session.close()


async def run_bot() -> None:
    raise RuntimeError(
        "Polling mode is disabled. Run `uvicorn main:app --host 0.0.0.0 --port $PORT` and use webhook mode."
    )
