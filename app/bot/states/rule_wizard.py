"""FSM states for the 'create search rule' wizard."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RuleWizard(StatesGroup):
    """Step-by-step collection of a new SearchRule's fields."""

    name = State()
    keywords = State()
    max_price = State()
    exclude = State()
    sites = State()
    interval = State()
