"""Tests for the flip tracker: money math, flip-only gate, lifecycle + stats."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.bot.formatting import net_flip_profit
from app.database import session as db
from app.database.base import Base
from app.database.models import FlipStatus, Listing
from app.database.models.enums import SiteName
from app.services import flips
from app.services.flips import settings as flip_settings


# --- Money math (single formula for cards AND realised profit) -------------------------
def test_fees_and_net_profit(monkeypatch):
    monkeypatch.setattr(flip_settings, "resale_fee_percent", 10.0)
    monkeypatch.setattr(flip_settings, "resale_shipping_eur", 5.0)
    assert flips.fees_for_sale(1000) == 105.0            # 10% + 5 € shipping
    assert flips.net_profit(700, 1000) == 195.0          # 1000 − 105 − 700
    assert flips.estimated_net_profit(700, 1000) == 195.0
    # The deal-card estimate must use exactly the same math.
    assert net_flip_profit(700, 1000) == 195.0


def test_flip_mode_gate(monkeypatch):
    monkeypatch.setattr(flip_settings, "resale_fee_percent", 10.0)
    monkeypatch.setattr(flip_settings, "resale_shipping_eur", 5.0)
    assert flips.passes_flip_mode(700, 1000, None) is True       # mode off
    assert flips.passes_flip_mode(700, 1000, 100) is True        # 195 ≥ 100
    assert flips.passes_flip_mode(700, 1000, 300) is False       # 195 < 300
    assert flips.passes_flip_mode(700, None, 300) is True        # unknown market passes
    assert flips.passes_flip_mode(None, 1000, 300) is True


# --- Lifecycle on SQLite ------------------------------------------------------------------
@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def _listing(title: str, price: float) -> Listing:
    return Listing(
        rule_id=1, site=SiteName.KLEINANZEIGEN, external_id=title, fingerprint=title,
        title=title, url="https://www.kleinanzeigen.de/x", price=price,
        estimated_market_price=price * 1.4,
    )


def test_purchase_sale_and_stats(sqlite_db, monkeypatch):
    monkeypatch.setattr(flip_settings, "resale_fee_percent", 10.0)
    monkeypatch.setattr(flip_settings, "resale_shipping_eur", 5.0)

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[Base.metadata.tables["flips"]],
            )
        maker = db.get_sessionmaker()
        async with maker() as session:
            gpu = _listing("RTX 4090", 700)
            phone = _listing("iPhone 17 Pro", 500)

            f1 = await flips.record_purchase(session, 42, gpu, 700)
            f2 = await flips.record_purchase(session, 42, phone, 500)
            assert f1.status is FlipStatus.BOUGHT

            s = await flips.profit_stats(session, 42)
            assert s.open_count == 2 and s.invested_open == 1200.0
            assert s.sold_count == 0 and s.net_profit == 0.0

            await flips.record_sale(session, f1, 1000)   # net 195
            await flips.cancel_flip(session, f2)

            s = await flips.profit_stats(session, 42)
            assert s.open_count == 0
            assert s.sold_count == 1
            assert s.revenue == 1000.0 and s.fees == 105.0
            assert s.net_profit == 195.0 and s.net_last_30d == 195.0
            assert s.best_title == "RTX 4090" and s.best_net == 195.0
            assert s.avg_margin_pct == pytest.approx(27.9, abs=0.1)  # 195 / 700

            # Ownership scoping: another user cannot see this flip.
            assert await flips.get_flip(session, f1.id, 99) is None
            assert (await flips.get_flip(session, f1.id, 42)) is f1
        await db.dispose_engine()

    asyncio.run(scenario())
