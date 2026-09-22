"""The Mini App's detail endpoint, and who is allowed to open what.

The endpoint takes a listing id from the client, which makes it the one place
in this feature where another user's data could leak. It is scoped through the
rule's owner, and the test that matters is the one where somebody asks for a
find that is not theirs.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routers import webapp as api
from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, SearchRule, SiteName, User


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


@pytest.fixture(autouse=True)
def no_sold_comps(monkeypatch):
    async def none(rule_id, now=None):  # noqa: ANN001
        return []

    from app.services import sold_comps

    monkeypatch.setattr(sold_comps, "realised_comps", none)


async def _tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _owner_with_listing(session, tg: int, title: str, desc: str = ""):
    user = User(telegram_id=tg)
    session.add(user)
    await session.flush()
    rule = SearchRule(user_id=user.id, name="phones", keywords="iphone")
    session.add(rule)
    await session.flush()
    row = Listing(
        rule_id=rule.id, site=SiteName.KLEINANZEIGEN, external_id=f"e{tg}",
        fingerprint=f"fp{tg}", title=title, description=desc or None,
        url="https://example.com/x", price=500.0,
    )
    session.add(row)
    await session.flush()
    return user, row


def test_the_owner_gets_the_detail(sqlite_db):
    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user, row = await _owner_with_listing(
                session, 11, "iPhone 14 Pro", "Display defekt, Rest top"
            )
            await session.commit()
            out = await api.listing_detail_view(row.id, user=user, session=session)
        await db.dispose_engine()
        return out

    detail = asyncio.run(scenario())
    assert detail.listing.title == "iPhone 14 Pro"
    assert detail.description == "Display defekt, Rest top"
    assert detail.is_defective is True
    assert "defekt" in detail.defect_markers
    # The marketplace is named the way it spells itself, not as a slug.
    assert detail.listing.site_label == "Kleinanzeigen"


def test_another_user_s_find_does_not_resolve(sqlite_db):
    """A listing id is client input — the scope is the rule's owner, not the id."""

    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            _, mine = await _owner_with_listing(session, 21, "iPhone 14 Pro")
            stranger, _ = await _owner_with_listing(session, 22, "Fremdes Angebot")
            await session.commit()
            with pytest.raises(HTTPException) as caught:
                await api.listing_detail_view(mine.id, user=stranger, session=session)
        await db.dispose_engine()
        return caught.value

    assert asyncio.run(scenario()).status_code == 404


def test_an_unknown_id_is_a_404_not_a_crash(sqlite_db):
    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user, _ = await _owner_with_listing(session, 31, "iPhone 14 Pro")
            await session.commit()
            with pytest.raises(HTTPException) as caught:
                await api.listing_detail_view(999999, user=user, session=session)
        await db.dispose_engine()
        return caught.value

    assert asyncio.run(scenario()).status_code == 404


def test_a_lonely_listing_says_there_is_not_enough_to_compare(sqlite_db):
    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user, row = await _owner_with_listing(session, 41, "iPhone 14 Pro")
            await session.commit()
            out = await api.listing_detail_view(row.id, user=user, session=session)
        await db.dispose_engine()
        return out

    detail = asyncio.run(scenario())
    assert detail.compared_with == 0
    # No reference means the app shows "not enough data" instead of a median
    # computed from nothing.
    assert detail.reference is None
    assert detail.asking is not None and detail.asking.usable is False
