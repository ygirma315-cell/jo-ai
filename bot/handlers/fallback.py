from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot.keyboards.menu import main_menu_keyboard

router = Router(name="fallback")


@router.message(F.text)
async def fallback_text(message: Message, miniapp_url: str | None) -> None:
    await message.answer(
        "I did not understand that input. Please use the menu buttons.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )


@router.message()
async def fallback_any(message: Message) -> None:
    await message.answer("Please send text commands or use the menu buttons.")
