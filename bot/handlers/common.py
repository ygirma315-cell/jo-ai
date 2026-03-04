from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.constants import MENU_AI_TOOLS, MENU_CANCEL, MENU_HELP, MENU_UTILITIES
from bot.keyboards.menu import ai_tools_keyboard, main_menu_keyboard, utilities_keyboard
from bot.models.session import Feature
from bot.services.session_manager import SessionManager
from version import VERSION

router = Router(name="common")

WELCOME_TEXT = (
    "✨ <b>Welcome to JO AI Assistant</b>\n\n"
    "I can help you with:\n"
    "• 🤖 AI Chat and smart answers\n"
    "• ⚡ Code generation\n"
    "• 🔍 Research and analysis\n"
    "• 🎨 Image generation\n"
    "• 🧮 Calculator and 🎮 Games\n\n"
    "🧠 Ask me anything, or tap a menu button below to start."
)

HELP_TEXT = (
    "💡 <b>Help Center</b>\n\n"
    "🤖 <b>AI Commands</b>\n"
    "• /chat - JO AI chat mode\n"
    "• /code - code generator mode\n"
    "• /research - research mode\n"
    "• /prompt - prompt generator mode\n"
    "• /image - image generator mode\n"
    "• /deepseek - switch DeepSeek profile\n"
    "• /kimi - image describer (send photo)\n\n"
    "🛠️ <b>Other Features</b>\n"
    "• /calculator - safe calculator\n"
    "• /games - Tic-Tac-Toe and Guess Number\n"
    "• /menu - return to main menu\n\n"
    "📌 Tip: You can switch modes any time. Need a quick check? Use /ping."
)

MENU_HINT_TEXT = (
    "🏠 <b>Main Menu</b>\n\n"
    "Choose a section below:\n"
    "• 🤖 AI Tools\n"
    "• 🛠️ Utilities\n\n"
    "💡 Need guidance? Use /help"
)


@router.message(CommandStart())
async def handle_start(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(f"🤖 Bot Version: {VERSION}", reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(
        "🎯 <b>Quick Start</b>\n\n"
        "• Tap <b>🤖 AI Tools</b> to chat, code, research, generate prompts, or create images.\n"
        "• Tap <b>🛠️ Utilities</b> for calculator and games.\n\n"
        "🧠 Ask me anything when you're ready.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )


@router.message(Command("restart"))
async def handle_restart(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(
        "✅ <b>Session restarted</b>\n\n"
        "Your chat state is refreshed.\n"
        "Pick a mode from the menu to continue.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )


@router.message(Command("help"))
@router.message(F.text == MENU_HELP)
@router.message(F.text == "Help")
async def handle_help(message: Message, miniapp_url: str | None) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard(miniapp_url))


@router.message(Command("ping"))
async def handle_ping(message: Message) -> None:
    await message.answer("🏓 <b>Pong!</b>\n\n✅ Bot is online and ready.")


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
        "🤖 <b>AI Tools Menu</b>\n\n"
        "Choose what you want to do:\n"
        "• 💬 Chat AI\n"
        "• ⚡ Generate code\n"
        "• 🔍 Research\n"
        "• ✨ Build prompts\n"
        "• 🎨 Generate images\n"
        "• 🖼️ Describe images with Kimi",
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
        "🛠️ <b>Utilities Menu</b>\n\n"
        "• 🧮 Calculator for quick math\n"
        "• 🎮 Games for fun breaks\n\n"
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
        await message.answer("🏠 You are already in the main menu.", reply_markup=main_menu_keyboard(miniapp_url))
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
            await query.message.answer("🏠 Returned to main menu.", reply_markup=main_menu_keyboard(miniapp_url))
        await query.message.answer(MENU_HINT_TEXT, reply_markup=main_menu_keyboard(miniapp_url))
