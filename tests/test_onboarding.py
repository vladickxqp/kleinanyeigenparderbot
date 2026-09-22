"""The first minute: language, then straight to the first search.

The old flow ended at the main menu, and the main menu is where most people
stopped — nine buttons and no idea which one turns into a deal. Now the first
thing after picking a language is the first search, in one sentence.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.bot.handlers import settings as settings_view
from app.bot.texts import SUPPORTED_LANGUAGES, t
from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import SearchRule, User


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


async def _tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_a_user_with_no_searches_is_handed_the_first_one(sqlite_db, monkeypatch):
    monkeypatch.setattr(settings, "nl_rules_enabled", True)

    async def scenario() -> bool:
        await _tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=7001)
            session.add(user)
            await session.flush()
            return await settings_view.wants_first_rule(session, user)

    assert asyncio.run(scenario()) is True


def test_a_user_who_already_searches_gets_the_menu(sqlite_db, monkeypatch):
    monkeypatch.setattr(settings, "nl_rules_enabled", True)

    async def scenario() -> bool:
        await _tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=7002)
            session.add(user)
            await session.flush()
            session.add(SearchRule(user_id=user.id, name="gpu", keywords="rtx 4090"))
            await session.flush()
            return await settings_view.wants_first_rule(session, user)

    assert asyncio.run(scenario()) is False


def test_without_the_sentence_path_the_menu_stays(sqlite_db, monkeypatch):
    # The eight-question wizard is what people give up on; it is not what a
    # brand-new user should be dropped into unasked.
    monkeypatch.setattr(settings, "nl_rules_enabled", False)

    async def scenario() -> bool:
        await _tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=7003)
            session.add(user)
            await session.flush()
            return await settings_view.wants_first_rule(session, user)

    assert asyncio.run(scenario()) is False


def test_the_first_rule_prompt_exists_and_shows_an_example_in_every_language():
    for lang in SUPPORTED_LANGUAGES:
        text = t("start.first_rule", lang)
        assert text != "start.first_rule"
        assert "Tesla Model 3" in text  # the example the sentence parser understands
