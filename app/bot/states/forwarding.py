"""FSM state for choosing the channel deal cards are copied to."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ForwardSetup(StatesGroup):
    """Waiting for a forwarded post, an @name or a chat id."""

    target = State()
