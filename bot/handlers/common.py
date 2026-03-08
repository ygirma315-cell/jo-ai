from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.constants import MENU_AI_TOOLS, MENU_CANCEL, MENU_HELP, MENU_UTILITIES, MENU_VERSION_MODELS
from bot.keyboards.menu import ai_tools_keyboard, main_menu_keyboard, utilities_keyboard
from bot.models.session import Feature
from bot.runtime_info import format_release_summary_html, format_runtime_info_html
from bot.security import DEVELOPER_HANDLE
from bot.services.session_manager import SessionManager

router = Router(name="common")

WELCOME_TEXT = (
    "\u2728 <b>Welcome to JO AI Assistant</b>\n\n"
    "I can help you with:\n"
    "\u2022 \U0001F916 AI chat and smart answers\n"
    "\u2022 \u26A1 Code generation\n"
    "\u2022 \U0001F50D Research and analysis\n"
    "\u2022 \U0001F3A8 Image generation\n"
    "\u2022 \U0001F5BC\ufe0f Vision mode for image description\n"
    "\u2022 \U0001F9EE Calculator and \U0001F3AE Games\n\n"
    "\U0001F9E0 Ask me anything, or tap a menu button below to start."
)

HELP_TEXT = (
    "\U0001F4A1 <b>Help Center</b>\n\n"
    "\U0001F916 <b>AI Commands</b>\n"
    "\u2022 /chat - JO AI chat mode\n"
    "\u2022 /code - code generator mode\n"
    "\u2022 /research - research mode\n"
    "\u2022 /prompt - prompt generator mode\n"
    "\u2022 /image - image generator mode\n"
    "\u2022 /analysis - deep analysis mode\n"
    "\u2022 /vision - vision mode (send photo)\n\n"
    "\U0001F6E0\ufe0f <b>Other Features</b>\n"
    "\u2022 /calculator - safe calculator\n"
    "\u2022 /games - Tic-Tac-Toe and Guess Number\n"
    "\u2022 /version - show public version info\n"
    "\u2022 /menu - return to main menu\n\n"
    "Internal backend, provider, and model details are not shared.\n"
    f"For JO API access, contact {DEVELOPER_HANDLE}."
)

MENU_HINT_TEXT = (
    "\U0001F3E0 <b>Main Menu</b>\n\n"
    "Choose a section below:\n"
    "\u2022 \U0001F916 AI Tools\n"
    "\u2022 \U0001F6E0\ufe0f Utilities\n\n"
    "\U0001F4A1 Need guidance? Use /help"
)


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
        "\U0001F3AF <b>Quick Start</b>\n\n"
        "\u2022 Tap <b>\U0001F916 AI Tools</b> to chat, code, research, build prompts, create images, or use vision mode.\n"
        "\u2022 Tap <b>\U0001F6E0\ufe0f Utilities</b> for calculator and games.\n"
        "\u2022 Tap <b>\u2139\ufe0f Version</b> for public build info.\n\n"
        "\U0001F9E0 Ask me anything when you're ready.",
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
        "\u2705 <b>Session restarted</b>\n\n"
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
    await message.answer("\U0001F3D3 <b>Pong!</b>\n\n\u2705 Bot is online and ready.")


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
    await message.answer(
        "\U0001F916 <b>AI Tools Menu</b>\n\n"
        "Choose what you want to do:\n"
        "\u2022 \U0001F4AC Chat AI\n"
        "\u2022 \u26A1 Generate code\n"
        "\u2022 \U0001F50D Research\n"
        "\u2022 \u2728 Build prompts\n"
        "\u2022 \U0001F3A8 Generate images\n"
        "\u2022 \U0001F5BC\ufe0f Vision mode",
        reply_markup=ai_tools_keyboard(),
    )


@router.message(Command("utilities"))
@router.message(F.text == MENU_UTILITIES)
@router.message(F.text == "Utilities")
async def handle_utilities_menu(
    message: Message, session_manager: SessionManager, miniapp_url: str | None
) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.UTILITIES_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(
        "\U0001F6E0\ufe0f <b>Utilities Menu</b>\n\n"
        "\u2022 \U0001F9EE Calculator for quick math\n"
        "\u2022 \U0001F3AE Games for fun breaks\n\n"
        "Pick one below.",
        reply_markup=utilities_keyboard(),
    )


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
        await message.answer("\U0001F3E0 You are already in the main menu.", reply_markup=main_menu_keyboard(miniapp_url))
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
            await query.message.answer("\U0001F3E0 Returned to main menu.", reply_markup=main_menu_keyboard(miniapp_url))
        await query.message.answer(MENU_HINT_TEXT, reply_markup=main_menu_keyboard(miniapp_url))
