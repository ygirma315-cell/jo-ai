from __future__ import annotations

from dataclasses import dataclass
import random
import secrets

from bot.models.session import TicTacToeState


WIN_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


@dataclass(frozen=True)
class TicTacToeOutcome:
    status: str  # continue | player_win | bot_win | draw
    bot_move: int | None = None


class TicTacToeService:
    def new_game(self) -> TicTacToeState:
        return TicTacToeState(game_id=secrets.token_hex(3))

    def apply_player_turn(self, state: TicTacToeState, position: int) -> TicTacToeOutcome:
        if state.finished:
            raise ValueError("This game already ended.")
        if position < 0 or position > 8:
            raise ValueError("That move is outside the board.")
        if state.board[position] != " ":
            raise ValueError("That cell is already taken.")

        state.board[position] = "X"
        winner = self._winner(state.board)
        if winner == "X":
            state.finished = True
            return TicTacToeOutcome(status="player_win")
        if self._is_draw(state.board):
            state.finished = True
            return TicTacToeOutcome(status="draw")

        bot_position = self._pick_bot_move(state.board)
        state.board[bot_position] = "O"
        winner = self._winner(state.board)
        if winner == "O":
            state.finished = True
            return TicTacToeOutcome(status="bot_win", bot_move=bot_position)
        if self._is_draw(state.board):
            state.finished = True
            return TicTacToeOutcome(status="draw", bot_move=bot_position)

        return TicTacToeOutcome(status="continue", bot_move=bot_position)

    def _pick_bot_move(self, board: list[str]) -> int:
        for position in self._empty_cells(board):
            if self._would_win(board, position, "O"):
                return position

        for position in self._empty_cells(board):
            if self._would_win(board, position, "X"):
                return position

        if board[4] == " ":
            return 4

        corners = [index for index in (0, 2, 6, 8) if board[index] == " "]
        if corners:
            return random.choice(corners)

        sides = [index for index in (1, 3, 5, 7) if board[index] == " "]
        if sides:
            return random.choice(sides)

        raise ValueError("No valid moves available.")

    def _would_win(self, board: list[str], position: int, symbol: str) -> bool:
        if board[position] != " ":
            return False
        test_board = board[:]
        test_board[position] = symbol
        return self._winner(test_board) == symbol

    def _empty_cells(self, board: list[str]) -> list[int]:
        return [index for index, value in enumerate(board) if value == " "]

    def _winner(self, board: list[str]) -> str | None:
        for a, b, c in WIN_LINES:
            if board[a] != " " and board[a] == board[b] == board[c]:
                return board[a]
        return None

    def _is_draw(self, board: list[str]) -> bool:
        return self._winner(board) is None and all(cell != " " for cell in board)

