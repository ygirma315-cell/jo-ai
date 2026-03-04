from __future__ import annotations

from dataclasses import dataclass
import random
import secrets

from bot.models.session import GuessNumberState


@dataclass(frozen=True)
class GuessResult:
    status: str  # low | high | correct
    attempts: int


class GuessNumberService:
    def new_game(self, min_value: int = 1, max_value: int = 100) -> GuessNumberState:
        return GuessNumberState(
            game_id=secrets.token_hex(3),
            target=random.randint(min_value, max_value),
            min_value=min_value,
            max_value=max_value,
            attempts=0,
            finished=False,
        )

    def process_guess(self, state: GuessNumberState, guess: int) -> GuessResult:
        if state.finished:
            raise ValueError("This game already ended.")
        if guess < state.min_value or guess > state.max_value:
            raise ValueError(f"Please pick a number between {state.min_value} and {state.max_value}.")

        state.attempts += 1

        if guess < state.target:
            return GuessResult(status="low", attempts=state.attempts)
        if guess > state.target:
            return GuessResult(status="high", attempts=state.attempts)

        state.finished = True
        return GuessResult(status="correct", attempts=state.attempts)

