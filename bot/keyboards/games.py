from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.session import TicTacToeState


def tic_tac_toe_board_keyboard(state: TicTacToeState) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, value in enumerate(state.board):
        if value == " ":
            label = str(index + 1)
            callback_data = f"ttt:{state.game_id}:{index}"
        else:
            label = value
            callback_data = "ttt:noop"
        builder.button(text=label, callback_data=callback_data)
    builder.button(text="🛑 End Game", callback_data="menu:main")
    builder.adjust(3, 3, 3, 1)
    return builder.as_markup()


def tic_tac_toe_end_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Play Again", callback_data="ttt:replay")
    builder.button(text="🎮 Games Menu", callback_data="gm:open")
    builder.button(text="🏠 Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def guess_number_end_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Play Again", callback_data="gn:replay")
    builder.button(text="🎮 Games Menu", callback_data="gm:open")
    builder.button(text="🏠 Main Menu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()
