from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.constants import CALCULATOR_EXAMPLE, MENU_BUTTON_TEXTS, MENU_CALCULATOR
from bot.filters.feature_filter import ActiveFeatureFilter
from bot.keyboards.menu import main_menu_keyboard
from bot.models.session import Feature
from bot.services.calculator_service import CalculatorError, CalculatorService
from bot.services.session_manager import SessionManager

router = Router(name="calculator")

CALCULATOR_INTRO = (
    "Calculator mode is ready.\n"
    "Supported: +, -, *, /, parentheses, decimals.\n"
    f"Example: <code>{CALCULATOR_EXAMPLE}</code>\n\n"
    "Send an expression now."
)


@router.message(Command("calculator"))
@router.message(F.text == MENU_CALCULATOR)
async def open_calculator(message: Message, session_manager: SessionManager, miniapp_url: str | None) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.CALCULATOR)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await message.answer(CALCULATOR_INTRO, reply_markup=main_menu_keyboard(miniapp_url))


@router.message(
    ActiveFeatureFilter(Feature.CALCULATOR),
    F.text,
    ~F.text.in_(MENU_BUTTON_TEXTS),
    ~F.text.startswith("/"),
)
async def evaluate_expression(
    message: Message,
    calculator_service: CalculatorService,
    miniapp_url: str | None,
) -> None:
    expression = (message.text or "").strip()
    try:
        result = calculator_service.evaluate(expression)
    except CalculatorError as exc:
        await message.answer(
            f"{exc}\nTry something like: <code>{CALCULATOR_EXAMPLE}</code>",
            reply_markup=main_menu_keyboard(miniapp_url),
        )
        return

    await message.answer(f"Result: <code>{result}</code>", reply_markup=main_menu_keyboard(miniapp_url))


@router.message(ActiveFeatureFilter(Feature.CALCULATOR), ~F.text)
async def calculator_unexpected_input(message: Message, miniapp_url: str | None) -> None:
    await message.answer(
        f"Please send a text expression. Example: <code>{CALCULATOR_EXAMPLE}</code>",
        reply_markup=main_menu_keyboard(miniapp_url),
    )
