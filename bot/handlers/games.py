from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.constants import MENU_BUTTON_TEXTS, MENU_GAMES
from bot.filters.feature_filter import ActiveFeatureFilter
from bot.keyboards.games import (
    guess_number_end_keyboard,
    tic_tac_toe_board_keyboard,
    tic_tac_toe_end_keyboard,
)
from bot.keyboards.menu import games_menu_keyboard, main_menu_keyboard
from bot.models.session import Feature, GuessNumberState, TicTacToeState
from bot.services.guess_number_service import GuessNumberService
from bot.services.session_manager import SessionManager
from bot.services.tictactoe_service import TicTacToeOutcome, TicTacToeService

router = Router(name="games")


async def _send_games_menu(message: Message) -> None:
    await message.answer(
        "🎮 <b>Games Menu</b>\n\nChoose a game to play:",
        reply_markup=games_menu_keyboard(),
    )


def _tictactoe_text(state: TicTacToeState, outcome: TicTacToeOutcome | None = None) -> str:
    header = "❌⭕ <b>Tic-Tac-Toe</b>\nYou are <b>X</b>. Bot is <b>O</b>."
    if outcome is None or outcome.status == "continue":
        if outcome and outcome.bot_move is not None:
            return f"{header}\n🤖 Bot played at cell {outcome.bot_move + 1}. Your turn."
        return f"{header}\n🎯 Tap an empty cell to play."
    if outcome.status == "player_win":
        return f"{header}\n🏆 <b>You won.</b>"
    if outcome.status == "bot_win":
        return f"{header}\n🤖 <b>Bot won this round.</b>"
    return f"{header}\n🤝 <b>Draw.</b>"


async def _start_tictactoe(
    message: Message,
    user_id: int,
    session_manager: SessionManager,
    tictactoe_service: TicTacToeService,
) -> None:
    async with session_manager.lock(user_id) as session:
        session.tic_tac_toe = tictactoe_service.new_game()
        state = session.tic_tac_toe

    await message.answer(
        _tictactoe_text(state),
        reply_markup=tic_tac_toe_board_keyboard(state),
    )


async def _start_guess_number(
    message: Message,
    user_id: int,
    session_manager: SessionManager,
    guess_number_service: GuessNumberService,
    miniapp_url: str | None,
) -> None:
    async with session_manager.lock(user_id) as session:
        session.guess_number = guess_number_service.new_game()
        state = session.guess_number

    await message.answer(
        "🎯 <b>Guess the Number started</b>\n"
        f"I picked a number between {state.min_value} and {state.max_value}.\n"
        "Send your first guess.",
        reply_markup=main_menu_keyboard(miniapp_url),
    )


@router.message(Command("games"))
@router.message(F.text == MENU_GAMES)
@router.message(F.text == "Games")
async def open_games_menu(
    message: Message,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    if not message.from_user:
        return

    transition = await session_manager.switch_feature(message.from_user.id, Feature.GAMES_MENU)
    if transition.notice:
        await message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
    await _send_games_menu(message)


@router.callback_query(F.data == "gm:open")
async def open_games_menu_callback(
    query: CallbackQuery,
    session_manager: SessionManager,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    transition = await session_manager.switch_feature(query.from_user.id, Feature.GAMES_MENU)
    await query.answer()

    if isinstance(query.message, Message):
        if transition.notice and transition.previous != Feature.GAMES_MENU:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await _send_games_menu(query.message)


@router.callback_query(F.data == "gm:ttt")
async def start_tictactoe_callback(
    query: CallbackQuery,
    session_manager: SessionManager,
    tictactoe_service: TicTacToeService,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    transition = await session_manager.switch_feature(query.from_user.id, Feature.TIC_TAC_TOE)
    await query.answer()

    if isinstance(query.message, Message):
        if transition.notice and transition.previous != Feature.GAMES_MENU:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await _start_tictactoe(query.message, query.from_user.id, session_manager, tictactoe_service)


@router.callback_query(F.data == "gm:guess")
async def start_guess_number_callback(
    query: CallbackQuery,
    session_manager: SessionManager,
    guess_number_service: GuessNumberService,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    transition = await session_manager.switch_feature(query.from_user.id, Feature.GUESS_NUMBER)
    await query.answer()

    if isinstance(query.message, Message):
        if transition.notice and transition.previous != Feature.GAMES_MENU:
            await query.message.answer(transition.notice, reply_markup=main_menu_keyboard(miniapp_url))
        await _start_guess_number(
            query.message, query.from_user.id, session_manager, guess_number_service, miniapp_url
        )


@router.callback_query(F.data == "ttt:replay")
async def replay_tictactoe(
    query: CallbackQuery,
    session_manager: SessionManager,
    tictactoe_service: TicTacToeService,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    await session_manager.switch_feature(query.from_user.id, Feature.TIC_TAC_TOE)
    await query.answer()
    if isinstance(query.message, Message):
        await _start_tictactoe(query.message, query.from_user.id, session_manager, tictactoe_service)


@router.callback_query(F.data == "ttt:noop")
async def tictactoe_noop(query: CallbackQuery) -> None:
    await query.answer("⚠️ That cell is already taken.")


@router.callback_query(F.data.startswith("ttt:"))
async def tictactoe_move(
    query: CallbackQuery,
    session_manager: SessionManager,
    tictactoe_service: TicTacToeService,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    raw_data = query.data or ""
    parts = raw_data.split(":")
    if len(parts) != 3:
        await query.answer("⚠️ Invalid move payload.", show_alert=True)
        return

    _, game_id, cell_raw = parts
    try:
        cell = int(cell_raw)
    except ValueError:
        await query.answer("⚠️ Invalid move payload.", show_alert=True)
        return

    state: TicTacToeState | None = None
    outcome: TicTacToeOutcome | None = None
    error_text: str | None = None

    async with session_manager.lock(query.from_user.id) as session:
        if session.active_feature != Feature.TIC_TAC_TOE or session.tic_tac_toe is None:
            error_text = "That game session expired. Start a new game."
        else:
            state = session.tic_tac_toe
            if state.game_id != game_id:
                error_text = "That game session expired. Start a new game."
            else:
                try:
                    outcome = tictactoe_service.apply_player_turn(state, cell)
                except ValueError as exc:
                    error_text = str(exc)

    if error_text:
        await query.answer(error_text, show_alert=False)
        return

    await query.answer("✅ Move received.")
    if not isinstance(query.message, Message) or state is None or outcome is None:
        return

    final = outcome.status in {"player_win", "bot_win", "draw"}
    text = _tictactoe_text(state, outcome)
    keyboard = tic_tac_toe_end_keyboard() if final else tic_tac_toe_board_keyboard(state)

    with suppress(TelegramBadRequest):
        await query.message.edit_text(text, reply_markup=keyboard)
        return
    await query.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "gn:replay")
async def replay_guess_number(
    query: CallbackQuery,
    session_manager: SessionManager,
    guess_number_service: GuessNumberService,
    miniapp_url: str | None,
) -> None:
    if not query.from_user:
        await query.answer()
        return

    await session_manager.switch_feature(query.from_user.id, Feature.GUESS_NUMBER)
    await query.answer()
    if isinstance(query.message, Message):
        await _start_guess_number(
            query.message, query.from_user.id, session_manager, guess_number_service, miniapp_url
        )


@router.message(
    ActiveFeatureFilter(Feature.GUESS_NUMBER),
    F.text,
    ~F.text.in_(MENU_BUTTON_TEXTS),
    ~F.text.startswith("/"),
)
async def process_guess_number(
    message: Message,
    session_manager: SessionManager,
    guess_number_service: GuessNumberService,
) -> None:
    if not message.from_user:
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("✍️ Please send a whole number like <code>42</code>.")
        return

    guess = int(text)
    result_status = ""
    result_attempts = 0
    min_value = 1
    max_value = 100
    game_finished = False
    session_expired = False
    processing_error: str | None = None

    async with session_manager.lock(message.from_user.id) as session:
        if session.active_feature != Feature.GUESS_NUMBER or session.guess_number is None:
            session_expired = True
        else:
            state: GuessNumberState = session.guess_number
            min_value, max_value = state.min_value, state.max_value
            try:
                guess_result = guess_number_service.process_guess(state, guess)
            except ValueError as exc:
                processing_error = str(exc)
            else:
                result_status = guess_result.status
                result_attempts = guess_result.attempts
                game_finished = state.finished

    if session_expired:
        await message.answer("⏳ That game session expired. Please start a new one.")
        return
    if processing_error:
        await message.answer(processing_error)
        return

    if result_status == "low":
        await message.answer(f"📉 Too low. Try a higher number ({min_value}-{max_value}).")
        return
    if result_status == "high":
        await message.answer(f"📈 Too high. Try a lower number ({min_value}-{max_value}).")
        return

    if game_finished:
        await message.answer(
            f"🎉 Correct! You guessed it in {result_attempts} attempt(s).",
            reply_markup=guess_number_end_keyboard(),
        )


@router.message(ActiveFeatureFilter(Feature.GUESS_NUMBER), ~F.text)
async def guess_number_unexpected_message(message: Message) -> None:
    await message.answer("✍️ Please send your guess as plain text digits (for example: <code>57</code>).")
