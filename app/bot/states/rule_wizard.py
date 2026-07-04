"""FSM states for the 'create search rule' wizard."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RuleWizard(StatesGroup):
    """Step-by-step collection of a new SearchRule's fields."""

    name = State()
    keywords = State()
    category = State()
    max_price = State()
    exclude = State()
    location = State()
    radius = State()
    sites = State()
    interval = State()


class EditWizard(StatesGroup):
    """Edit a single field of an existing rule (rule id kept in FSM data)."""

    name = State()
    keywords = State()
    category = State()
    price = State()
    exclude = State()
    location = State()
    radius = State()
    interval = State()
    min_score = State()
