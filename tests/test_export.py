"""The CSV export a Profi rule was sold with.

The file has to open cleanly in the spreadsheet of a German, Russian or
English reader, and a scraped title must never run as a formula in it.
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, SearchRule, SiteName, User
from app.database.models.enums import DealVerdict
from app.services import export

NOW = datetime(2026, 9, 24, 9, 30, tzinfo=timezone.utc)


def _row(title: str, price: float | None, **extra) -> Listing:
    row = Listing(
        rule_id=1, site=SiteName.KLEINANZEIGEN, external_id=title, fingerprint=title,
        title=title, url="https://example.com/x", price=price,
        estimated_market_price=extra.pop("market", None),
        discount_percent=extra.pop("discount", None),
        deal_score=extra.pop("score", 0), deal_verdict=extra.pop("verdict", DealVerdict.FAIR),
        is_favorite=extra.pop("favorite", False), location=extra.pop("location", None),
        seller_name=extra.pop("seller", None), created_at=NOW,
    )
    row.rule = SearchRule(user_id=1, name="PS5 Jagd", keywords="ps5")
    return row


def _parse(blob: bytes) -> list[list[str]]:
    text = blob.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


# --- The file -----------------------------------------------------------------------
def test_it_opens_in_excel_bom_semicolons_and_crlf():
    blob = export.to_csv([_row("PS5 Slim", 300.0)], "de")
    assert blob.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in blob
    header = _parse(blob)[0]
    assert header[:4] == ["Gefunden am", "Suche", "Plattform", "Titel"]


def test_headers_follow_the_reader_s_language():
    assert _parse(export.to_csv([], "en"))[0][:3] == ["Found at", "Search", "Marketplace"]
    assert _parse(export.to_csv([], "ru"))[0][3] == "Название"
    assert _parse(export.to_csv([], "uk"))[0][3] == "Назва"


def test_decimals_follow_the_reader_s_language():
    row = _row("PS5", 299.5, market=350.0, discount=14.4)
    de = _parse(export.to_csv([row], "de"))[1]
    en = _parse(export.to_csv([row], "en"))[1]
    price = export.COLUMNS.index("price")
    discount = export.COLUMNS.index("discount")
    assert de[price] == "299,50" and de[discount] == "14,4"
    assert en[price] == "299.50" and en[discount] == "14.4"


def test_every_column_is_filled_from_the_row():
    row = _row("PS5 Slim OVP", 300.0, market=380.0, discount=21.1, score=88,
               verdict=DealVerdict.GREAT, favorite=True, location="Worms", seller="Max")
    cells = dict(zip(export.COLUMNS, _parse(export.to_csv([row], "de"))[1]))
    assert cells["found_at"] == "2026-09-24 09:30"
    assert cells["rule"] == "PS5 Jagd"
    assert cells["site"] == "Kleinanzeigen"
    assert cells["title"] == "PS5 Slim OVP"
    assert cells["score"] == "88"
    assert cells["verdict"] == "great"
    assert cells["location"] == "Worms"
    assert cells["seller"] == "Max"
    assert cells["favorite"] == "ja"
    assert cells["url"] == "https://example.com/x"


def test_a_missing_price_is_an_empty_cell_not_a_word():
    cells = dict(zip(export.COLUMNS, _parse(export.to_csv([_row("VB", None)], "de"))[1]))
    assert cells["price"] == ""
    assert cells["market"] == ""


def test_a_scraped_title_cannot_become_a_formula():
    row = _row("=HYPERLINK(\"http://evil\";\"click\")", 10.0, seller="+491234")
    cells = dict(zip(export.COLUMNS, _parse(export.to_csv([row], "de"))[1]))
    assert cells["title"].startswith("'=")
    assert cells["seller"].startswith("'+")
    # Numbers are ours and stay numbers — a negative discount must not be quoted.
    cells = dict(zip(export.COLUMNS, _parse(export.to_csv([_row("x", 10.0, discount=-5.0)], "en"))[1]))
    assert cells["discount"] == "-5.0"


def test_a_single_rule_export_drops_the_repeating_rule_column():
    header = _parse(export.to_csv([_row("PS5", 1.0)], "de", include_rule=False))[0]
    assert "Suche" not in header
    assert len(header) == len(export.COLUMNS) - 1


def test_the_file_name_is_plain_ascii():
    name = export.filename("Bürostühle & Tische — günstig", NOW)
    assert name == "funde-burostuhle-tische-gunstig-2026-09-24.csv"
    # Nothing ASCII survives: fall back to a name rather than an empty slug.
    assert export.filename("Приставки", NOW) == "funde-export-2026-09-24.csv"


# --- Which rows -----------------------------------------------------------------------
@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def _stored(rule_id: int, ext: str, title: str) -> Listing:
    return Listing(
        rule_id=rule_id, site=SiteName.KLEINANZEIGEN, external_id=ext, fingerprint=ext,
        title=title, url=f"https://example.com/{ext}", price=100.0,
    )


def test_rows_are_scoped_to_the_owner_and_newest_first(sqlite_db):
    async def scenario():
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.get_sessionmaker()() as session:
            me = User(telegram_id=1)
            other = User(telegram_id=2)
            session.add_all([me, other])
            await session.flush()
            mine = SearchRule(user_id=me.id, name="mine", keywords="a")
            mine2 = SearchRule(user_id=me.id, name="mine2", keywords="b")
            theirs = SearchRule(user_id=other.id, name="theirs", keywords="c")
            session.add_all([mine, mine2, theirs])
            await session.flush()
            session.add(_stored(mine.id, "1", "first"))
            session.add(_stored(mine.id, "2", "second"))
            session.add(_stored(mine2.id, "3", "elsewhere"))
            session.add(_stored(theirs.id, "4", "not yours"))
            await session.commit()

            by_rule = await export.rows_for_rule(session, mine.id, me.id)
            foreign = await export.rows_for_rule(session, theirs.id, me.id)
            everything = await export.rows_for_user(session, me.id)
            capped = await export.rows_for_user(session, me.id, limit=2)
            # The rule name is loaded with the row: the sheet needs it and an
            # async session cannot fetch it lazily.
            names = [r.rule.name for r in everything]
        await db.dispose_engine()
        return by_rule, foreign, everything, capped, names

    by_rule, foreign, everything, capped, names = asyncio.run(scenario())
    assert [r.title for r in by_rule] == ["second", "first"]
    assert foreign == []
    assert {r.title for r in everything} == {"first", "second", "elsewhere"}
    assert len(capped) == 2
    assert set(names) == {"mine", "mine2"}
