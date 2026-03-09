from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.constants import MENU_AI_TOOLS, MENU_CANCEL, MENU_HELP, MENU_VERSION_MODELS
from bot.keyboards.menu import ai_tools_keyboard, main_menu_keyboard
from bot.models.session import Feature
from bot.runtime_info import format_release_summary_html, format_runtime_info_html
from bot.security import DEVELOPER_HANDLE
from bot.services.session_manager import SessionManager

router = Router(name="common")

WELCOME_TEXT = (
    "<b>Welcome to JO AI Assistant</b>\n\n"
    "I can help you with:\n"
    "- AI chat and smart answers\n"
    "- Code generation\n"
    "- Research and analysis\n"
    "- Image generation\n"
    "- Vision mode for image description\n"
    "- Text-to-Speech generation\n"
    "- Mini App access from Telegram\n\n"
    "Ask me anything, or tap a menu button below to start."
)

HELP_TEXT = (
    "<b>Help Center</b>\n\n"
    "<b>AI Commands</b>\n"
    "/chat - JO AI chat mode\n"
    "/code - code generator mode\n"
    "/research - research mode\n"
    "/prompt - prompt generator mode\n"
    "/image - image generator mode\n"
    "/analysis - deep analysis mode\n"
    "/vision - vision mode (send photo)\n"
    "/tts - text-to-speech mode\n\n"
    "<b>Other Commands</b>\n"
    "/version - show public version info\n"
    "/menu - return to main menu\n\n"
    "Internal backend, provider, and model details are not shared.\n"
    f"For JO API access, contact {DEVELOPER_HANDLE}."
)

MENU_HINT_TEXT = (
    "<b>Main Menu</b>\n\n"
    "Choose a section below:\n"
    "- AI Tools\n"
    "- Open App\n"
    "- Version\n\n"
    "Need guidance? Use /help"
)

AI_TOOLS_TEXT = (
    "<b>AI Tools Menu</b>\n\n"
    "Choose what you want to do:\n"
    "- Chat AI\n"
    "- Generate code\n"
    "- Research\n"
    "- Build prompts\n"
    "- Generate images\n"
    "- Vision mode\n"
    "- Text-to-Speech"
)


async def _send_ai_tools_menu(message: Message) -> None:
    await message.answer(AI_TOOLS_TEXT, reply_markup=ai_tools_keyboard())


@router.message(CommandStart())
async def handle_start(
    message: Message,
    session_manager: SessionManager,
    miniapp_url: str | None,
    runtime_info: dict[str, object],
) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(format_release_summary_html(runtime_info), reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(
        "<b>Quick Start</b>\n\n"
        "- Tap <b>AI Tools</b> to chat, code, research, build prompts, create images, use vision, or generate speech.\n"
        "- Tap <b>Open App</b> to launch the Mini App directly from Telegram.\n"
        "- Tap <b>Version</b> for public build info.\n\n"
        "Ask me anything when you're ready.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )


@router.message(Command("restart"))
async def handle_restart(
    message: Message,
    session_manager: SessionManager,
    miniapp_url: str | None,
    runtime_info: dict[str, object],
) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(
        "<b>Session restarted</b>\n\n"
        "Your chat state is refreshed.\n"
        "Pick a mode from the menu to continue.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )
    await message.answer(format_release_summary_html(runtime_info), reply_markup=main_menu_keyboard(miniapp_url))


@router.message(Command("help"))
@router.message(F.text == MENU_HELP)
@router.message(F.text == "Help")
async def handle_help(message: Message, miniapp_url: str | None) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard(miniapp_url))


@router.message(Command("ping"))
async def handle_ping(message: Message) -> None:
    await message.answer("<b>Pong!</b>\n\nBot is online and ready.")


@router.message(Command("version"))
@router.message(Command("models"))
@router.message(F.text == MENU_VERSION_MODELS)
async def handle_version(
    message: Message,
    runtime_info: dict[str, object],
) -> None:
    await message.answer(format_runtime_info_html(runtime_info, active_profile=None))


@router.message(Command("aitools"))
@router.message(F.text == MENU_AI_TOOLS)
@router.message(F.text == "AI Tools")
async def handle_ai_tools_menu(
    message: Message, session_manager: SessionManager, miniapp_url: str | None
) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.AI_TOOLS_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await _send_ai_tools_menu(message)


@router.message(Command("menu"))
@router.message(Command("cancel"))
@router.message(F.text == MENU_CANCEL)
@router.message(F.text == "Cancel / Back to Menu")
async def handle_menu(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    else:
        await message.answer("You are already in the main menu.", reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(MENU_HINT_TEXT, reply_markup=main_menu_keyboard(miniapp_url))


@router.callback_query(F.data == "menu:main")
async def handle_menu_callback(query: CallbackQuery, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not query.from_user:
        await query.answer()
        return

    transition = await session_manager.switch_feature(query.from_user.id, Feature.NONE)
    await query.answer()
    if isinstance(query.message, Message):
        if transition.notice:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        else:
            await query.message.answer("Returned to main menu.", reply_markup=main_menu_keyboard(miniapp_url))
        await query.message.answer(MENU_HINT_TEXT, reply_markup=main_menu_keyboard(miniapp_url))


@router.callback_query(F.data == "menu:ai_tools")
async def handle_ai_tools_callback(
    query: CallbackQuery,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    transition = await session_manager.switch_feature(query.from_user.id, Feature.AI_TOOLS_MENU)
    await query.answer()
    if isinstance(query.message, Message):
        if transition.notice:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await _send_ai_tools_menu(query.message)
