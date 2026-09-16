"""Tests for roles, coupons, referrals and the free trial (SQLite in-memory)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import SubscriptionTier, User, UserRole
from app.services import coupons as coupon_svc
from app.services import referrals as referral_svc
from app.services import roles

# --- Roles ---------------------------------------------------------------------


def _user(role: UserRole = UserRole.USER, tg: int = 1) -> User:
    return User(telegram_id=tg, role=role, subscription=SubscriptionTier.FREE)


def test_role_hierarchy():
    owner = _user(UserRole.OWNER)
    admin = _user(UserRole.ADMIN)
    mod = _user(UserRole.MODERATOR)
    plain = _user(UserRole.USER)

    assert roles.has_role(owner, UserRole.OWNER)
    assert roles.has_role(admin, UserRole.MODERATOR)
    assert not roles.has_role(admin, UserRole.OWNER)
    assert roles.has_role(mod, UserRole.MODERATOR)
    assert not roles.has_role(mod, UserRole.ADMIN)
    assert not roles.has_role(plain, UserRole.MODERATOR)


def test_env_admin_ids_bootstrap_owner(monkeypatch):
    monkeypatch.setattr(roles, "settings", SimpleNamespace(admin_ids=[999]))
    bootstrap_owner = _user(UserRole.USER, tg=999)
    assert roles.effective_role(bootstrap_owner) is UserRole.OWNER
    assert roles.has_role(bootstrap_owner, UserRole.OWNER)
    normal = _user(UserRole.USER, tg=1000)
    assert roles.effective_role(normal) is UserRole.USER


# --- Coupons: pure logic -----------------------------------------------------------


def test_discounted_price_percent_and_fixed(monkeypatch):
    from app.services.coupons import discounted_price_stars

    monkeypatch.setattr(coupon_svc.settings, "pro_price_stars", 250)
    percent = SimpleNamespace(discount_percent=20, discount_fixed_stars=None)
    fixed = SimpleNamespace(discount_percent=None, discount_fixed_stars=100)
    brutal = SimpleNamespace(discount_percent=None, discount_fixed_stars=9999)

    assert discounted_price_stars(percent) == 200
    assert discounted_price_stars(fixed) == 150
    assert discounted_price_stars(brutal) == 1  # never below 1 star


# --- DB-backed flows ----------------------------------------------------------------


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


async def _setup() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Base.metadata.tables["users"],
                Base.metadata.tables["subscriptions"],
                Base.metadata.tables["search_rules"],
                Base.metadata.tables["payments"],
                Base.metadata.tables["coupons"],
                Base.metadata.tables["coupon_redemptions"],
                Base.metadata.tables["referrals"],
            ],
        )


def test_coupon_lifecycle(sqlite_db):
    async def scenario() -> None:
        await _setup()
        maker = db.get_sessionmaker()
        async with maker() as session:
            coupon = await coupon_svc.create_coupon(
                session, code="test10", created_by=1,
                discount_percent=10, max_uses=1,
            )
            assert coupon.code == "TEST10"  # normalised to uppercase

            # Two benefits at once must be rejected.
            with pytest.raises(coupon_svc.CouponError):
                await coupon_svc.create_coupon(
                    session, code="BAD", created_by=1,
                    discount_percent=10, free_days=5,
                )

            # Valid for user 42 …
            ok = await coupon_svc.validate_coupon(session, "TEST10", 42)
            assert ok.id == coupon.id
            await coupon_svc.mark_redeemed(session, coupon, 42)

            # … but not twice for the same user (and max_uses=1 is exhausted).
            with pytest.raises(coupon_svc.CouponError):
                await coupon_svc.validate_coupon(session, "TEST10", 42)
            with pytest.raises(coupon_svc.CouponError):
                await coupon_svc.validate_coupon(session, "TEST10", 43)

            # Expired coupons are rejected.
            old = await coupon_svc.create_coupon(
                session, code="OLD", created_by=1, discount_percent=5,
                valid_until=datetime.now(timezone.utc) - timedelta(days=1),
            )
            assert old is not None
            with pytest.raises(coupon_svc.CouponError):
                await coupon_svc.validate_coupon(session, "OLD", 42)
        await db.dispose_engine()

    asyncio.run(scenario())


def test_referral_flow(sqlite_db):
    async def scenario() -> None:
        await _setup()
        maker = db.get_sessionmaker()
        async with maker() as session:
            inviter = User(telegram_id=100, subscription=SubscriptionTier.FREE)
            invited = User(telegram_id=200, subscription=SubscriptionTier.FREE)
            session.add_all([inviter, invited])
            await session.flush()

            # Self-referrals and double referrals are rejected.
            assert await referral_svc.register_referral(session, 200, 200) is False
            assert await referral_svc.register_referral(session, 100, 200) is True
            assert await referral_svc.register_referral(session, 999, 200) is False

            # First purchase of the invited user rewards the inviter once.
            rewarded_tg = await referral_svc.reward_referrer_if_due(session, invited)
            assert rewarded_tg == 100
            assert inviter.subscription is SubscriptionTier.PRO

            # A second payment must not reward again.
            assert await referral_svc.reward_referrer_if_due(session, invited) is None
        await db.dispose_engine()

    asyncio.run(scenario())


def test_referral_payload_parsing():
    assert referral_svc.parse_referral_payload("ref12345") == 12345
    assert referral_svc.parse_referral_payload("refabc") is None
    assert referral_svc.parse_referral_payload("xyz") is None
    assert referral_svc.parse_referral_payload(None) is None
    link = referral_svc.build_referral_link("dealbot", 42)
    assert link == "https://t.me/dealbot?start=ref42"


def test_trial_only_once(sqlite_db):
    async def scenario() -> None:
        from app.database.models import PlanType
        from app.services.premium import activate_premium, has_used_trial

        await _setup()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=300, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            assert await has_used_trial(session, 300) is False
            await activate_premium(
                session, user, days=7, provider="trial", plan=PlanType.TRIAL
            )
            assert user.subscription is SubscriptionTier.PRO
            assert await has_used_trial(session, 300) is True
        await db.dispose_engine()

    asyncio.run(scenario())
