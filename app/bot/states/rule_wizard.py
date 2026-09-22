"""FSM states for the 'create search rule' wizard."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RuleWizard(StatesGroup):
    """Step-by-step collection of a new SearchRule's fields."""

    #: The short path: one sentence instead of the eight questions below.
    sentence = State()
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
    """Edit a single field of an existing rule (rule id kept in FSM data).

    The three filter states below exist only here: the creation wizard already
    asks eight questions before it shows a single result.
    """

    name = State()
    keywords = State()
    category = State()
    price = State()
    exclude = State()
    location = State()
    radius = State()
    interval = State()
    min_score = State()
    condition = State()
    shipping = State()
    auctions = State()
    seller = State()
    #: Kilometres and first registration in one step — a car hunter sets both
    #: or neither, and the menu is long enough already.
    vehicle = State()
