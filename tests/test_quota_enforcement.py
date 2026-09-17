"""The four places where a usage quota is actually spent.

Cards, photo valuations, quick searches and negotiation suggestions all meter
against Redis in production; here the counters are replaced by an in-memory
stand-in so the tests exercise the ENFORCEMENT, not the storage.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.bot import notifier
from app.bot.handlers import listings as listings_handler
from app.bot.handlers import photo_eval, quick_search
from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import (
    Listing,
    Notification,
    SearchRule,
    SiteName,
    SubscriptionTier,
    User,
)
from app.parsers.schemas import ParsedListing
from app.services import quiet, quota, throttle, vision
from app.services.vision import PhotoAssessment


# --- Doubles ----------------------------------------------------------------------------
class FakeQuota:
    """The Redis counters, in memory — same contract, no infrastructure."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used: dict[str, int] = {}
        self.released: list[str] = []
        #: The window each refund was booked against, so a test can prove the
        #: unit went back where it came from.
        self.refunded: list[str] = []

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(quota, "check", self.check)
        monkeypatch.setattr(quota, "consume", self.consume)
        monkeypatch.setattr(quota, "release", self.release)

    # The real windowing is used rather than re-implemented: a double that
    # invents its own day boundary cannot catch a refund landing on the wrong
    # side of midnight, which is the bug these counters are prone to.
    @staticmethod
    def window(kind: str, now=None) -> str:  # noqa: ANN001
        return quota._stamp(quota._WINDOW[kind], now)

    async def check(self, kind, user, now=None):  # noqa: ANN001
        return quota.QuotaState(
            kind=kind,
            used=self.used.get(kind, 0),
            limit=self.limit,
            stamp=self.window(kind, now),
        )

    async def consume(self, kind, user, *, amount=1, now=None):  # noqa: ANN001
        stamp = self.window(kind, now)
        used = self.used.get(kind, 0)
        if used + amount > self.limit >= 0:
            return quota.QuotaState(
                kind=kind, used=used, limit=self.limit, stamp=stamp
            )
        self.used[kind] = used + amount
        return quota.QuotaState(
            kind=kind, used=self.used[kind], limit=self.limit, stamp=stamp
        )

    async def release(self, kind, user, *, amount=1, now=None, stamp=None):  # noqa: ANN001
        self.released.append(kind)
        self.refunded.append(stamp or self.window(kind, now))
        self.used[kind] = max(0, self.used.get(kind, 0) - amount)


class FakeBot:
    """Collects what would have gone to Telegram; cards carry a keyboard."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.cards: list[str] = []
        self.notices: list[str] = []
        self.session = SimpleNamespace(close=self._close)

    async def _close(self) -> None:
        return None

    #: How many times the next card should be answered with a flood wait.
    flood: int = 0

    async def send_message(self, chat_id, text, **kwargs):  # noqa: ANN001
        if kwargs.get("reply_markup") is None:
            self.notices.append(text)
            return None
        if self.flood:
            from aiogram.exceptions import TelegramRetryAfter

            self.flood -= 1
            raise TelegramRetryAfter(
                method=None, message="Flood control exceeded", retry_after=1
            )
        if self.fail:
            raise RuntimeError("Telegram sagt nein")
        self.cards.append(text)
        return None


class FakeStatus:
    def __init__(self) -> None:
        self.text: str | None = None

    async def edit_text(self, text, **kwargs):  # noqa: ANN001
        self.text = text
        return None


class FakeMessage:
    def __init__(self, caption: str | None = None) -> None:
        self.caption = caption
        self.photo = [SimpleNamespace(file_id="photo-1")]
        self.answers: list[str] = []
        self.status = FakeStatus()
        self.bot = SimpleNamespace(download=self._download)

    async def _download(self, photo, destination=None):  # noqa: ANN001
        return None

    async def answer(self, text, **kwargs):  # noqa: ANN001
        self.answers.append(text)
        return self.status


class FakeState:
    def __init__(self) -> None:
        self.data: dict = {}

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)


class FakeParser:
    requires_browser = False

    async def collect(self, query):  # noqa: ANN001
        return [
            ParsedListing(
                site=SiteName.KLEINANZEIGEN,
                external_id="1",
                title="Tesla Model 3 Long Range",
                url="https://example.com/1",
                price=25000.0,
                posted_at=datetime.now(timezone.utc),
            )
        ]


def _install_bot(monkeypatch, *, fail: bool = False) -> FakeBot:
    bot = FakeBot(fail=fail)
    monkeypatch.setattr(notifier, "Bot", lambda *a, **k: bot)
    return bot


def _silence_infrastructure(monkeypatch) -> None:
    """No Redis in the test suite: guard, counters and quiet hours are stubbed."""

    async def never_quiet(telegram_id, now=None):  # noqa: ANN001
        return False

    async def no_duplicate(chat_id, listing):  # noqa: ANN001
        return False

    async def no_counter():
        return None

    monkeypatch.setattr(quiet, "is_quiet_now", never_quiet)
    monkeypatch.setattr(notifier, "_duplicate_send", no_duplicate)
    monkeypatch.setattr(notifier, "_count_sent", no_counter)
    # Telegram's one-message-per-second pacing is real; waiting it out in a
    # test only makes the suite slow.
    monkeypatch.setattr(notifier, "PER_CHAT_PACE_SECONDS", 0)


def _install_cooldown(monkeypatch) -> list[str]:
    """First call for a key is free, every later one reports time left."""
    seen: list[str] = []

    async def fake_cooldown(key, seconds):  # noqa: ANN001
        if key in seen:
            return seconds
        seen.append(key)
        return 0

    monkeypatch.setattr(throttle, "cooldown", fake_cooldown)
    return seen


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
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Base.metadata.tables["users"],
                Base.metadata.tables["search_rules"],
                Base.metadata.tables["listings"],
                Base.metadata.tables["notifications"],
            ],
        )


def _listing(rule_id: int, external_id: str, title: str, **kwargs) -> Listing:
    data = {
        "rule_id": rule_id,
        "site": SiteName.KLEINANZEIGEN,
        "external_id": external_id,
        "fingerprint": f"fp-{external_id}",
        "title": title,
        "url": f"https://example.com/{external_id}",
        "price": 500.0,
        "deal_score": 50,
    }
    data.update(kwargs)
    return Listing(**data)


# --- 1. Deal cards ----------------------------------------------------------------------
def test_card_cap_withholds_the_rest_and_teases_exactly_once(sqlite_db, monkeypatch):
    """Over the cap: hold the card back, name the best one, once a day."""
    FakeQuota(limit=1).install(monkeypatch)
    _silence_infrastructure(monkeypatch)
    _install_cooldown(monkeypatch)
    bot = _install_bot(monkeypatch)
    monkeypatch.setattr(settings, "notification_cap_teaser_enabled", True)

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=42, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="gpu", keywords="rtx 4090")
            session.add(rule)
            await session.flush()
            first = _listing(rule.id, "a", "RTX 4090 Founders Edition")
            best = _listing(
                rule.id, "b", "RTX 4080 Super", price=500.0,
                estimated_market_price=700.0, deal_score=88,
            )
            later = _listing(rule.id, "c", "RTX 4070")
            session.add_all([first, best, later])
            await session.commit()
            ids = [first.id, best.id, later.id]

        assert await notifier.notify_user_about_listings(42, ids[:2], "de") == 1

        async with maker() as session:
            delivered = await session.get(Listing, ids[0])
            held = await session.get(Listing, ids[1])
            assert delivered.notified is True and delivered.notified_at is not None
            assert delivered.withheld is False
            # notified=True as well: flush_unnotified() would loop on it forever.
            assert held.withheld is True and held.notified is True
            assert held.notified_at is None

        assert len(bot.cards) == 1
        assert len(bot.notices) == 1
        teaser = bot.notices[0]
        assert "🔒 Tageslimit erreicht" in teaser
        assert "1 weiterer Treffer heute" in teaser
        assert "RTX 4080 Super" in teaser
        assert "ca. +103 € netto" in teaser        # 700 - 13% - 5,90 € - 500
        assert "/premium" in teaser

        # A second capped batch stays silent: one teaser per user per day.
        assert await notifier.notify_user_about_listings(42, ids[2:], "de") == 0
        assert len(bot.notices) == 1
        async with maker() as session:
            assert (await session.get(Listing, ids[2])).withheld is True

        await db.dispose_engine()

    asyncio.run(scenario())


def test_teaser_can_be_switched_off(sqlite_db, monkeypatch):
    FakeQuota(limit=0).install(monkeypatch)
    _silence_infrastructure(monkeypatch)
    _install_cooldown(monkeypatch)
    bot = _install_bot(monkeypatch)
    monkeypatch.setattr(settings, "notification_cap_teaser_enabled", False)

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=43, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="gpu", keywords="rtx")
            session.add(rule)
            await session.flush()
            row = _listing(rule.id, "a", "RTX 4090")
            session.add(row)
            await session.commit()
            listing_id = row.id

        assert await notifier.notify_user_about_listings(43, [listing_id], "de") == 0
        assert bot.notices == [] and bot.cards == []
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_flood_wait_is_waited_out_not_counted_as_a_failure(sqlite_db, monkeypatch):
    """Telegram asking us to slow down is not a card that cannot be delivered.

    Reporting it as an error refunds the quota and hands the same card back to
    the rescue sweep, which retries the whole batch at the same speed — into
    the next flood wait. The user sees their deals arrive late, on repeat.
    """
    fake = FakeQuota(limit=10)
    fake.install(monkeypatch)
    _silence_infrastructure(monkeypatch)
    _install_cooldown(monkeypatch)
    bot = _install_bot(monkeypatch)
    bot.flood = 1  # the first attempt is refused, the retry goes through

    slept: list[float] = []

    async def no_wait(seconds):  # noqa: ANN001
        slept.append(seconds)

    monkeypatch.setattr(notifier.asyncio, "sleep", no_wait)

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=45, subscription=SubscriptionTier.PRO)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="gpu", keywords="rtx")
            session.add(rule)
            await session.flush()
            row = _listing(rule.id, "a", "RTX 4090 Founders Edition")
            session.add(row)
            await session.commit()
            listing_id = row.id

        assert await notifier.notify_user_about_listings(45, [listing_id], "de") == 1
        assert len(bot.cards) == 1
        # It waited, and it waited longer than Telegram asked for.
        assert slept and max(slept) >= 1

        async with maker() as session:
            rows = (await session.execute(select(Notification))).scalars().all()
            assert [r.is_sent for r in rows] == [True]
            assert rows[0].error is None
            assert (await session.get(Listing, listing_id)).notified is True
        # The user is billed once, for the card that really arrived.
        assert fake.used[quota.KIND_CARDS] == 1
        assert fake.released == []
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_hopeless_flood_wait_goes_back_to_the_sweep(sqlite_db, monkeypatch):
    fake = FakeQuota(limit=10)
    fake.install(monkeypatch)
    _silence_infrastructure(monkeypatch)
    _install_cooldown(monkeypatch)
    bot = _install_bot(monkeypatch)
    bot.flood = 5  # refused again and again

    async def no_wait(seconds):  # noqa: ANN001
        return None

    monkeypatch.setattr(notifier.asyncio, "sleep", no_wait)

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=46, subscription=SubscriptionTier.PRO)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="gpu", keywords="rtx")
            session.add(rule)
            await session.flush()
            row = _listing(rule.id, "a", "RTX 4090 Founders Edition")
            session.add(row)
            await session.commit()
            listing_id = row.id

        assert await notifier.notify_user_about_listings(46, [listing_id], "de") == 0
        async with maker() as session:
            # Not delivered, not billed, and left for the sweep to pick up.
            assert (await session.get(Listing, listing_id)).notified is False
        assert fake.released == [quota.KIND_CARDS]
        await db.dispose_engine()

    asyncio.run(scenario())


def test_every_delivery_attempt_is_written_to_notifications(sqlite_db, monkeypatch):
    """The audit table exists; success and failure both belong in it."""
    fake = FakeQuota(limit=10)
    fake.install(monkeypatch)
    _silence_infrastructure(monkeypatch)
    _install_cooldown(monkeypatch)
    bot = _install_bot(monkeypatch, fail=True)

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=44, subscription=SubscriptionTier.PRO)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="gpu", keywords="rtx")
            session.add(rule)
            await session.flush()
            row = _listing(rule.id, "a", "RTX 4090 Founders Edition")
            session.add(row)
            await session.commit()
            listing_id, user_id = row.id, user.id

        assert await notifier.notify_user_about_listings(44, [listing_id], "de") == 0

        async with maker() as session:
            failed = (await session.execute(select(Notification))).scalars().all()
            assert len(failed) == 1
            assert failed[0].is_sent is False
            assert failed[0].user_id == user_id
            assert failed[0].listing_id == listing_id
            assert "Telegram sagt nein" in failed[0].error
            assert (await session.get(Listing, listing_id)).notified is False

        # The user must not be billed for a crash on our side — and the refund
        # has to name the window the unit was booked in, because a batch that
        # starts at 23:59 finishes after midnight and would otherwise leave
        # yesterday's counter inflated forever.
        assert fake.released == [quota.KIND_CARDS]
        assert fake.refunded == [fake.window(quota.KIND_CARDS)]
        assert fake.used[quota.KIND_CARDS] == 0

        bot.fail = False
        assert await notifier.notify_user_about_listings(44, [listing_id], "de") == 1

        async with maker() as session:
            rows = (
                await session.execute(
                    select(Notification).order_by(Notification.id)
                )
            ).scalars().all()
            assert [r.is_sent for r in rows] == [False, True]
            assert rows[1].title == "RTX 4090 Founders Edition"
            assert rows[1].error is None

        await db.dispose_engine()

    asyncio.run(scenario())


# --- 2. Photo valuation -----------------------------------------------------------------
def _photo_user() -> User:
    return User(telegram_id=7, subscription=SubscriptionTier.FREE)


def _enable_photo_ai(monkeypatch) -> None:
    monkeypatch.setattr(settings, "photo_ai_premium_only", False)
    monkeypatch.setattr("app.services.ai.is_available", lambda: True)


def test_photo_quota_is_refunded_when_the_analysis_fails(monkeypatch):
    fake = FakeQuota(limit=1)
    fake.install(monkeypatch)
    _enable_photo_ai(monkeypatch)

    async def unrecognised(image_b64, media_type="image/jpeg", caption=None):  # noqa: ANN001
        return None

    monkeypatch.setattr(vision, "assess_photo", unrecognised)

    message = FakeMessage()
    asyncio.run(photo_eval.on_photo(message, _photo_user(), "de"))

    assert "nicht sicher erkennen" in message.status.text
    assert sorted(fake.released) == [quota.KIND_PHOTO, quota.KIND_PHOTO_DAY]
    assert fake.used[quota.KIND_PHOTO] == 0


def test_photo_crash_refunds_the_unit(monkeypatch):
    fake = FakeQuota(limit=1)
    fake.install(monkeypatch)
    _enable_photo_ai(monkeypatch)

    async def boom(image_b64, media_type="image/jpeg", caption=None):  # noqa: ANN001
        raise RuntimeError("vision kaputt")

    monkeypatch.setattr(vision, "assess_photo", boom)

    with pytest.raises(RuntimeError):
        asyncio.run(photo_eval.on_photo(FakeMessage(), _photo_user(), "de"))
    assert fake.used[quota.KIND_PHOTO] == 0


def test_photo_result_names_what_is_left_and_the_cap_explains_itself(monkeypatch):
    fake = FakeQuota(limit=1)
    fake.install(monkeypatch)
    _enable_photo_ai(monkeypatch)
    monkeypatch.setattr(photo_eval, "registry", [])

    async def recognised(image_b64, media_type="image/jpeg", caption=None):  # noqa: ANN001
        return PhotoAssessment(
            product="Sony WH-1000XM5",
            search_query="sony wh-1000xm5",
            est_value_eur=250.0,
            confidence="high",
            notes="",
        )

    monkeypatch.setattr(vision, "assess_photo", recognised)

    user = _photo_user()
    first = FakeMessage()
    asyncio.run(photo_eval.on_photo(first, user, "de"))
    assert "Sony WH-1000XM5" in first.status.text
    assert "Noch <b>0</b> von 1 Foto-Bewertungen diesen Monat" in first.status.text
    assert fake.used[quota.KIND_PHOTO] == 1

    # Free gets exactly one per month — the second try must say so, not fail mute.
    second = FakeMessage()
    asyncio.run(photo_eval.on_photo(second, user, "de"))
    assert second.status.text is None
    assert "aufgebraucht" in second.answers[-1]
    assert "/premium" in second.answers[-1]
    assert fake.used[quota.KIND_PHOTO] == 1


# --- 3. Quick search --------------------------------------------------------------------
def _install_quick_search(monkeypatch) -> None:
    async def no_wait(telegram_id, seconds=None, scope="manual"):  # noqa: ANN001
        return 0

    monkeypatch.setattr(quick_search, "manual_run_allowed", no_wait)
    monkeypatch.setattr(quick_search, "registry", [FakeParser()])


def test_quick_search_footer_counts_down_and_blocks_when_empty(monkeypatch):
    fake = FakeQuota(limit=2)
    fake.install(monkeypatch)
    _install_quick_search(monkeypatch)

    user = User(telegram_id=8, subscription=SubscriptionTier.FREE)
    command = SimpleNamespace(args="tesla model 3")

    first = FakeMessage()
    asyncio.run(quick_search.cmd_suche(first, user, command, FakeState()))
    assert "Tesla Model 3 Long Range" in first.status.text
    assert "Noch <b>1</b> von 2 Schnell-Suchen heute" in first.status.text

    second = FakeMessage()
    asyncio.run(quick_search.cmd_suche(second, user, command, FakeState()))
    assert "Noch <b>0</b> von 2 Schnell-Suchen heute" in second.status.text
    assert "/premium" in second.status.text

    third = FakeMessage()
    asyncio.run(quick_search.cmd_suche(third, user, command, FakeState()))
    assert third.status.text is None          # the search never ran
    assert "aufgebraucht" in third.answers[-1]
    assert fake.used[quota.KIND_QUICK] == 2


def test_quick_search_uses_the_tier_cooldown(monkeypatch):
    fake = FakeQuota(limit=5)
    fake.install(monkeypatch)
    _install_quick_search(monkeypatch)
    seen: list[int | None] = []

    async def record(telegram_id, seconds=None, scope="manual"):  # noqa: ANN001
        seen.append(seconds)
        return 0

    monkeypatch.setattr(quick_search, "manual_run_allowed", record)

    user = User(telegram_id=9, subscription=SubscriptionTier.PRO)
    asyncio.run(
        quick_search.cmd_suche(
            FakeMessage(), user, SimpleNamespace(args="tesla model 3"), FakeState()
        )
    )
    assert seen == [settings.pro_quick_search_cooldown_seconds]


# --- 4. Negotiation helper --------------------------------------------------------------
class FakeCallback:
    def __init__(self, listing_id: int) -> None:
        self.data = f"listing:nego:{listing_id}"
        self.message = FakeMessage()
        self.alerts: list[str] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        if text:
            self.alerts.append(text)


def test_negotiation_is_metered_and_explains_the_cap(sqlite_db, monkeypatch):
    fake = FakeQuota(limit=1)
    fake.install(monkeypatch)

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=11, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="gpu", keywords="rtx")
            session.add(rule)
            await session.flush()
            row = _listing(rule.id, "a", "RTX 4090", price=800.0)
            session.add(row)
            await session.flush()

            cb = FakeCallback(row.id)
            await listings_handler.cb_negotiate(cb, user, session, "de")
            assert "Verhandlungs-Vorschlag" in cb.message.answers[0]
            assert "Noch <b>0</b> von 1 Verhandlungen diesen Monat" in cb.message.answers[0]

            blocked = FakeCallback(row.id)
            await listings_handler.cb_negotiate(blocked, user, session, "de")
            assert "aufgebraucht" in blocked.message.answers[0]
            assert "/premium" in blocked.message.answers[0]
            assert fake.used[quota.KIND_NEGO] == 1

        await db.dispose_engine()

    asyncio.run(scenario())
