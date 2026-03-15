from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.constants import MENU_AI_TOOLS, MENU_CANCEL, MENU_HELP, MENU_REFERRAL, MENU_VERSION_MODELS
from bot.keyboards.menu import ai_tools_keyboard, main_menu_keyboard
from bot.models.session import Feature
from bot.runtime_info import format_release_summary_html, format_runtime_info_html
from bot.security import DEVELOPER_HANDLE
from bot.services.session_manager import SessionManager
from bot.services.tracking_service import SupabaseTrackingService, TrackingIdentity

router = Router(name="common")

WELCOME_TEXT = (
    "🤖 <b>Welcome to JO AI Assistant</b>\n\n"
    "Pick a lane and let's move:\n"
    "• 💬 AI chat and smart answers\n"
    "• 💠 Gemini mode (temporarily disabled)\n"
    "• ⚡ Code generation and debugging\n"
    "• 🔍 Research and deeper analysis\n"
    "• 🎨 Image generation and vision help\n"
    "• 🎬 Video generation\n"
    "• 🔊 Text-to-Speech output\n"
    "• 🎧 GPT Audio responses\n"
    "• 🔗 Referral links\n"
    "• 🚀 Mini App access from Telegram\n\n"
    "Tap a menu button below or send a message when you're ready."
)

HELP_TEXT = (
    "<b>Help Center</b>\n\n"
    "<b>AI Commands</b>\n"
    "/chat - JO AI chat mode\n"
    "/gemini - Gemini mode (temporarily disabled)\n"
    "/code - code generator mode\n"
    "/research - research mode\n"
    "/prompt - prompt generator mode\n"
    "/image - image generator mode\n"
    "/video - video generation mode\n"
    "/analysis - DeepSeek mode\n"
    "/deepseek - DeepSeek mode\n"
    "/vision - vision mode (send photo)\n"
    "/tts - text-to-speech mode\n"
    "/gptaudio - GPT Audio mode\n"
    "/referral - your invite link\n\n"
    "<b>Navigation</b>\n"
    "Back = one step back in the current feature\n"
    "Main Menu = return to the home menu\n\n"
    "<b>Other Commands</b>\n"
    "/version - show public version info\n"
    "/menu - return to main menu\n\n"
    "I am JO AI Chat, created by JO AI Chat / @GRPBUYER3.\n"
    "Internal backend, provider, and model details are not shared.\n"
    f"For JO API access, contact {DEVELOPER_HANDLE}."
)

MENU_HINT_TEXT = (
    "🏠 <b>Main Menu</b>\n\n"
    "Choose a section below:\n"
    "• 🤖 AI Tools\n"
    "• 🚀 Open App\n"
    "• 🔗 Referral\n"
    "• 💡 Help\n"
    "• ℹ️ Version\n\n"
    "Need guidance? Use /help."
)

AI_TOOLS_TEXT = (
    "🤖 <b>AI Tools Menu</b>\n\n"
    "Choose your workspace:\n"
    "• 💬 Chat AI\n"
    "• 💠 Gemini Chat (temporarily disabled)\n"
    "• ⚡ Generate code\n"
    "• 🔍 Research\n"
    "• ✨ Build prompts\n"
    "• 🧠 DeepSeek\n"
    "• 🎨 Generate images\n"
    "• 🎬 Generate videos\n"
    "• 🖼️ Vision mode\n"
    "• 🔊 Text-to-Speech\n"
    "• 🎧 GPT Audio"
)


async def _send_ai_tools_menu(message: Message) -> None:
    await message.answer(AI_TOOLS_TEXT, reply_markup=ai_tools_keyboard())


def _tracking_identity_from_message(message: Message) -> TrackingIdentity | None:
    if not message.from_user:
        return None
    return TrackingIdentity(
        telegram_id=int(message.from_user.id),
        username=(message.from_user.username or "").strip() or None,
        first_name=(message.from_user.first_name or "").strip() or None,
        last_name=(message.from_user.last_name or "").strip() or None,
    )


def _extract_referral_code_from_start(message_text: str | None) -> str | None:
    raw = str(message_text or "").strip()
    if not raw:
        return None
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return None
    token = parts[1].strip()
    if token.lower().startswith("ref_") or token.lower().startswith("ref-"):
        token = token[4:]
    cleaned = "".join(ch for ch in token if ch.isalnum() or ch in {"_", "-"})
    return cleaned[:64] or None


@router.message(CommandStart())
async def handle_start(
    message: Message,
    session_manager: SessionManager,
    miniapp_url: str | None,
    runtime_info: dict[str, object],
    tracking_service: SupabaseTrackingService | None = None,
) -> None:
    if not message.from_user:
        return

    referral_code = _extract_referral_code_from_start(message.text)
    identity = _tracking_identity_from_message(message)
    if identity and tracking_service and tracking_service.enabled:
        await tracking_service.track_action(
            identity=identity,
            message_type="start",
            user_message=(message.text or "/start"),
            bot_reply="Bot started",
            model_used=None,
            success=True,
            frontend_source="telegram_bot",
            feature_used="start",
            conversation_id=f"{identity.telegram_id}:start",
            text_content="Bot started",
            mark_started=True,
            started_via_referral=referral_code,
        )

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(format_release_summary_html(runtime_info), reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(
        "<b>Quick Start</b>\n\n"
        "- Tap <b>AI Tools</b> first to open chat, code, research, prompts, images, vision, or speech.\n"
        "- Tap <b>Open App</b> to launch the Mini App directly from Telegram.\n"
        "- Tap <b>Version</b> for public build info.\n\n"
        "Ask me anything when you're ready.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )
    if referral_code:
        await message.answer("✅ Referral detected and applied.", reply_markup=main_menu_keyboard(miniapp_url))


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


@router.message(Command("referral"))
@router.message(F.text == MENU_REFERRAL)
@router.message(F.text == "Referral")
async def handle_referral(
    message: Message,
    miniapp_url: str | None,
    tracking_service: SupabaseTrackingService | None = None,
) -> None:
    identity = _tracking_identity_from_message(message)
    if identity is None:
        await message.answer("Referral is available only in a Telegram user session.")
        return

    referral_code = str(identity.telegram_id)
    if tracking_service and tracking_service.enabled:
        referral_code = await tracking_service.ensure_referral_code(identity=identity, frontend_source="telegram_bot")
        await tracking_service.track_action(
            identity=identity,
            message_type="referral",
            user_message="/referral",
            bot_reply="Referral details shown",
            model_used=None,
            success=True,
            frontend_source="telegram_bot",
            feature_used="referral",
            conversation_id=f"{identity.telegram_id}:referral",
            text_content="Referral details shown",
            mark_started=True,
        )

    bot_username = ""
    try:
        me = await message.bot.get_me()
        bot_username = str(me.username or "").strip()
    except Exception:
        bot_username = ""

    telegram_link = f"https://t.me/{bot_username}?start={referral_code}" if bot_username else f"/start {referral_code}"
    mini_link = f"{miniapp_url}?ref={referral_code}" if miniapp_url else "Not configured"
    await message.answer(
        "<b>Your referral links</b>\n\n"
        f"Code: <code>{referral_code}</code>\n"
        f"Telegram: {telegram_link}\n"
        f"Mini App: {mini_link}\n\n"
        "Self-referrals and duplicate claims are ignored.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )


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
@router.message(F.text == "Main Menu")
@router.message(F.text == "Menu")
@router.message(F.text == "Cancel / Back to Menu")
async def handle_menu(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.NONE)
    if transition.previous != Feature.NONE:
        await message.answer("Returned to main menu.", reply_markup=main_menu_keyboard(miniapp_url))
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
        if transition.previous != Feature.NONE:
            await query.message.answer("Returned to main menu.", reply_markup=main_menu_keyboard(miniapp_url))
        else:
            await query.message.answer("You are already in the main menu.", reply_markup=main_menu_keyboard(miniapp_url))
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
