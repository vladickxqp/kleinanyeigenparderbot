"""One sentence into a finished search rule.

The wizard asks eight questions before anyone sees a single result, which is
where most people stop. This is the short path — and a short path that
misreads a price or invents a filter is worse than the eight questions, so the
deterministic layer is pinned down here field by field, the AI layer is pinned
down to *fill only*, and the round trip through FSM storage is treated with the
same suspicion as a model answer.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.bot.handlers import rules
from app.database import session as db
from app.database.base import Base
from app.database.models import SearchRule, SubscriptionTier, User
from app.database.models.enums import Condition
from app.services import ai, rule_nlp
from app.services.rule_nlp import RuleDraft, parse_rule_text


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(
        db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://")
    )
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def draft(text: str) -> RuleDraft:
    """The deterministic layer alone — no AI anywhere near it."""
    return parse_rule_text(text)


# --- What a sentence can say -----------------------------------------------------
def test_the_example_from_the_prompt_parses_completely():
    d = draft("Tesla Model 3 unter 25.000 Euro, 100 km um Worms, keine Unfallwagen")
    assert d.is_usable
    assert "tesla" in d.keywords.lower()
    assert d.max_price == 25000.0
    assert d.max_distance_km == 100
    assert d.location and "worms" in d.location.lower()
    assert any("unfall" in word.lower() for word in d.exclude_keywords)
    # The price does not survive as a keyword, or the search would look for the
    # digits in the ad title.
    assert "25" not in d.keywords


@pytest.mark.parametrize(
    "text, low, high",
    [
        ("iPhone 15 bis 800 €", None, 800.0),
        ("iPhone 15 unter 800 Euro", None, 800.0),
        ("iPhone 15 max 800", None, 800.0),
        ("iPhone 15 ab 300 €", 300.0, None),
        ("iPhone 15 zwischen 300 und 800 €", 300.0, 800.0),
        ("iPhone 15 300-800 €", 300.0, 800.0),
        ("iPhone 15 für 1.250,50 €", None, 1250.5),
    ],
)
def test_prices_are_read_the_way_people_write_them(text, low, high):
    d = draft(text)
    assert (d.min_price, d.max_price) == (low, high)


def test_a_reversed_range_is_straightened_out():
    d = draft("iPhone 15 zwischen 800 und 300 €")
    assert (d.min_price, d.max_price) == (300.0, 800.0)


def test_a_thousands_dot_is_not_a_decimal_point():
    # "1.200 €" is twelve hundred euros, not one euro twenty. Reading it the
    # other way makes every ad look like a steal.
    assert draft("Fahrrad bis 1.200 €").max_price == 1200.0


def test_distance_and_place_are_separated():
    d = draft("Fahrrad 50 km um Mannheim")
    assert d.max_distance_km == 50
    assert d.location and "mannheim" in d.location.lower()
    assert "50" not in d.keywords and "km" not in d.keywords.split()


def test_a_postcode_is_a_postcode_and_not_a_price():
    d = draft("Fahrrad in 67547, bis 300 €")
    assert d.zip_code == "67547"
    assert d.max_price == 300.0


def test_conditions_are_recognised():
    assert draft("PS5 neu OVP").condition is Condition.NEW
    assert draft("PS5 gebraucht").condition is Condition.USED
    assert draft("PS5 defekt Bastler").condition is Condition.DEFECTIVE
    assert draft("PS5").condition is Condition.ANY


def test_negations_become_exclusions_not_keywords():
    d = draft("Rennrad ohne Kratzer, keine Bastler")
    lowered = [word.lower() for word in d.exclude_keywords]
    assert "kratzer" in lowered and "bastler" in lowered
    assert "kratzer" not in d.keywords.lower()


def test_a_price_negation_stays_a_price():
    # "nicht über 800" is a bound, not a word to exclude.
    d = draft("Monitor nicht über 800 €")
    assert d.max_price == 800.0
    assert not any("800" in word for word in d.exclude_keywords)


def test_mileage_is_understood_even_though_nothing_filters_on_it():
    # Silently dropping it would be a lie, and turning it into a price would be
    # a disaster — 100.000 km is not a budget.
    d = draft("Golf höchstens 100.000 km, bis 9.000 €")
    assert d.max_mileage_km == 100000
    assert d.max_price == 9000.0


def test_a_sentence_with_nothing_to_search_for_is_not_usable():
    assert not draft("").is_usable
    assert not draft("   ").is_usable
    assert not draft("unter 500 €").is_usable


def test_a_bare_amount_with_a_currency_is_a_budget():
    # The last-resort reading, and the one people actually type. It used to
    # fire for "800 euro" and silently ignore "800 €".
    assert draft("iPhone 15 800 €").max_price == 800.0
    assert draft("iPhone 15 800 euro").max_price == 800.0
    assert draft("iPhone 15").max_price is None


def test_the_name_says_what_the_search_does():
    name = draft("RTX 4090 bis 1500 €").name
    assert name.lower().startswith("rtx 4090")
    assert "1500" in name.replace(".", "")


def test_absurd_input_is_bounded_not_rejected():
    d = draft("Sofa " + "x" * 5000)
    assert len(d.keywords) <= rule_nlp.MAX_KEYWORDS_CHARS
    assert len(d.name) <= rule_nlp.MAX_NAME_CHARS


# --- Storage round trip -----------------------------------------------------------
def test_a_draft_survives_storage_and_is_revalidated():
    original = draft("Tesla Model 3 bis 25.000 €, 100 km um Worms")
    restored = RuleDraft.from_dict(original.as_dict())
    assert restored.as_dict() == original.as_dict()


def test_storage_garbage_cannot_become_a_rule():
    # The round trip goes through an external store, so it is treated like a
    # model answer: every field re-validated, nothing trusted.
    hostile = RuleDraft.from_dict(
        {
            "keywords": "x" * 9000,
            "max_price": "sehr teuer",
            "min_price": -5,
            "max_distance_km": 99999,
            "condition": "nonsense",
            "exclude_keywords": ["ok", 7, None, "x" * 500],
            "zip_code": "abc",
        }
    )
    assert len(hostile.keywords) <= rule_nlp.MAX_KEYWORDS_CHARS
    assert hostile.max_price is None
    assert hostile.min_price is None
    assert hostile.condition is Condition.ANY
    assert hostile.zip_code is None
    assert all(isinstance(word, str) for word in hostile.exclude_keywords)
    assert RuleDraft.from_dict(None).is_usable is False
    assert RuleDraft.from_dict("not a dict").is_usable is False


# --- The AI layer may fill, never overwrite ---------------------------------------
def test_ai_values_only_fill_gaps():
    base = draft("Tesla Model 3 bis 25.000 €")
    merged = rule_nlp.merge_ai_fields(
        base,
        {"keywords": "etwas ganz anderes", "max_price": 999, "min_price": 5000},
    )
    # What the rules already found stands; only the empty field is filled.
    assert merged.max_price == 25000.0
    assert "tesla" in merged.keywords.lower()
    assert merged.min_price == 5000.0


def test_ai_values_go_through_the_same_validation():
    base = draft("Tesla Model 3")
    merged = rule_nlp.merge_ai_fields(
        base, {"max_price": "ganz viel", "max_distance_km": 10 ** 9, "condition": "???"}
    )
    assert merged.max_price is None
    assert merged.condition is Condition.ANY
    assert merged.max_distance_km is None or merged.max_distance_km <= 1000


def test_a_nonsense_answer_leaves_the_draft_alone():
    base = draft("Tesla Model 3 bis 25.000 €")
    for answer in (None, "", [], {"unknown_key": 1}, 42):
        merged = rule_nlp.merge_ai_fields(base, answer)
        assert merged.max_price == 25000.0
        assert merged.is_usable


def test_a_failing_model_call_still_yields_the_deterministic_draft(monkeypatch):
    async def boom(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("API down")

    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "ask", boom)
    result = asyncio.run(rule_nlp.build_draft("Tesla Model 3 bis 25.000 €"))
    assert result.max_price == 25000.0
    assert result.source == rule_nlp.SOURCE_RULES


def test_the_whole_feature_works_with_ai_switched_off(monkeypatch):
    monkeypatch.setattr(ai, "is_available", lambda: False)
    result = asyncio.run(rule_nlp.build_draft("Fahrrad bis 300 €"))
    assert result.max_price == 300.0
    assert result.is_usable


def test_a_model_answer_that_fills_a_gap_is_marked_as_such(monkeypatch):
    async def answer(system, prompt, **kwargs):  # noqa: ANN001
        return '{"location": "Worms", "max_distance_km": 50}'

    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "ask", answer)
    result = asyncio.run(rule_nlp.build_draft("Fahrrad bis 300 €"))
    assert result.location == "Worms"
    assert result.max_distance_km == 50
    assert result.source == rule_nlp.SOURCE_AI


# --- From the sentence to a saved rule --------------------------------------------
class FakeState:
    """The FSM, as far as these handlers use it."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})
        self.state: str | None = None
        self.cleared = False

    async def get_data(self) -> dict:
        return dict(self._data)

    async def update_data(self, **kwargs) -> None:
        self._data.update(kwargs)

    async def set_state(self, state) -> None:  # noqa: ANN001
        self.state = getattr(state, "state", state)

    async def clear(self) -> None:
        self.cleared = True
        self._data.clear()


class FakeMessage:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def answer(self, text, **kwargs):  # noqa: ANN001
        self.sent.append(text)
        return None


def test_the_summary_shows_every_field_the_sentence_carried():
    d = draft("Tesla Model 3 unter 25.000 €, 100 km um Worms, keine Unfallwagen")
    text = rules._draft_summary(d, "de")
    assert "25.000 €" in text or "25000 €" in text
    assert "Worms" in text and "100 km" in text
    assert "Unfall" in text or "unfall" in text


def test_the_summary_says_when_a_value_was_understood_but_cannot_be_used():
    # Mileage has no column to filter on. Dropping it silently would leave the
    # user believing the search honours it.
    d = draft("Golf höchstens 100.000 km bis 9.000 €")
    text = rules._draft_summary(d, "de")
    assert "100.000" in text


def test_the_summary_escapes_values_the_parser_never_saw():
    # The keyword extractor drops angle brackets, but a model answer and the
    # storage round trip do not go through it — and an unescaped "<" breaks
    # Telegram's HTML parser, so the message never arrives at all.
    hostile = RuleDraft.from_dict(
        {
            "keywords": "RTX <b>4090</b>",
            "name": "Suche & Co <i>",
            "location": "Worms <script>",
            "exclude_keywords": ["<b>bastler</b>"],
        }
    )
    text = rules._draft_summary(hostile, "de")
    assert "<b>4090</b>" not in text
    assert "<script>" not in text
    assert "&lt;b&gt;4090&lt;/b&gt;" in text
    assert "&amp; Co" in text


def test_the_summary_is_translated():
    d = draft("Fahrrad bis 300 €")
    assert rules._draft_summary(d, "en") != rules._draft_summary(d, "de")


def test_a_condition_out_of_storage_is_never_trusted():
    assert rules._stored_condition("new") is Condition.NEW
    assert rules._stored_condition("nonsense") is Condition.ANY
    assert rules._stored_condition(None) is Condition.ANY


def test_only_a_usable_draft_comes_back_out_of_storage():
    good = draft("Fahrrad bis 300 €")
    state = FakeState({"draft": good.as_dict()})
    assert asyncio.run(rules._stored_draft(state)) is not None
    # Nothing to search for: the buttons must not create a rule that would
    # match every ad on every site.
    empty = FakeState({"draft": {"keywords": "  "}})
    assert asyncio.run(rules._stored_draft(empty)) is None
    assert asyncio.run(rules._stored_draft(FakeState())) is None


def test_the_sentence_reaches_the_saved_rule(sqlite_db):
    """The wiring: what was understood is what ends up in the database."""

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=5150, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            d = draft("Tesla Model 3 unter 25.000 €, 100 km um Worms, keine Bastler")
            state = FakeState()
            await rules._apply_draft(state, d)
            message = FakeMessage()
            await rules._finalize(
                message, user, session, "de", state,
                exclude=list(d.exclude_keywords), sites=[], interval_seconds=600,
            )
            await session.flush()

            rule = (await session.execute(select(SearchRule))).scalars().one()
            assert rule.keywords == d.keywords
            assert rule.max_price == 25000.0
            assert rule.max_distance_km == 100
            assert rule.location and "worms" in rule.location.lower()
            assert any("bastler" in w.lower() for w in rule.exclude_keywords)
            assert rule.interval_seconds == 600
            assert rule.sites == []  # empty = every registered marketplace
            assert state.cleared and message.sent
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_condition_from_the_sentence_is_not_lost_on_the_way(sqlite_db):
    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=5151, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            d = draft("PS5 defekt bis 200 €")
            assert d.condition is Condition.DEFECTIVE
            state = FakeState()
            await rules._apply_draft(state, d)
            await rules._finalize(
                FakeMessage(), user, session, "de", state, exclude=[], sites=[],
            )
            await session.flush()
            rule = (await session.execute(select(SearchRule))).scalars().one()
            assert rule.condition is Condition.DEFECTIVE
        await db.dispose_engine()

    asyncio.run(scenario())


def test_the_step_by_step_wizard_still_creates_an_unfiltered_condition(sqlite_db):
    """The old path sets no condition — it must not inherit a stale one."""

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=5152, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()
            state = FakeState({"name": "Suche", "keywords": "rtx 4090"})
            await rules._finalize(
                FakeMessage(), user, session, "de", state, exclude=[], sites=[],
            )
            await session.flush()
            rule = (await session.execute(select(SearchRule))).scalars().one()
            assert rule.condition is Condition.ANY
        await db.dispose_engine()

    asyncio.run(scenario())
