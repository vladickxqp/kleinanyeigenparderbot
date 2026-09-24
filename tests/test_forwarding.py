"""Copying delivered deal cards into a channel — the Händler feature.

The level was sold with "Weiterleitung in Kanäle" and nothing forwarded. These
tests pin down who gets a copy (a target AND the feature), what the copy looks
like (card plus link, no owner-only buttons), and what happens when the
channel is lost (forget it, tell the owner once, never break the delivery).
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.config.settings import settings
from app.database.models import Listing, SiteName, SubscriptionTier, User
from app.database.models.enums import DealVerdict
from app.services import forwarding

CHANNEL = -1001234567890


@pytest.fixture(autouse=True)
def features(monkeypatch):
    monkeypatch.setattr(settings, "pro_features", "flip_mode,rule_power,export,market_report")
    monkeypatch.setattr(settings, "dealer_features", "flip_mode,rule_power,export,market_report,forwarding")


def _user(tier: SubscriptionTier = SubscriptionTier.UNLIMITED, target: int | None = CHANNEL) -> User:
    return User(telegram_id=42, subscription=tier, forward_chat_id=target, language_code="de")


def _listing(image: str | None = None) -> Listing:
    return Listing(
        id=5, rule_id=1, site=SiteName.KLEINANZEIGEN, external_id="777", fingerprint="f",
        title="PS5 Slim", url="https://example.com/777", price=300.0, image_url=image,
        estimated_market_price=400.0, deal_score=80, deal_verdict=DealVerdict.GREAT,
        discount_percent=25.0,
    )


class FakeBot:
    id = 999

    def __init__(self, *, chat=None, member=None, fail=None):
        self._chat = chat
        self._member = member
        self._fail = fail
        self.sent: list[tuple] = []

    async def get_chat(self, target):  # noqa: ANN001
        if isinstance(self._chat, Exception):
            raise self._chat
        return self._chat

    async def get_chat_member(self, chat_id, user_id):  # noqa: ANN001
        if isinstance(self._member, Exception):
            raise self._member
        return self._member

    async def send_message(self, chat_id, text, **kw):  # noqa: ANN001
        if self._fail is not None and chat_id == CHANNEL:
            raise self._fail
        self.sent.append(("message", chat_id, text, kw))
        return SimpleNamespace(message_id=1)

    async def send_photo(self, chat_id, photo, caption=None, **kw):  # noqa: ANN001
        if self._fail is not None and chat_id == CHANNEL:
            raise self._fail
        self.sent.append(("photo", chat_id, caption, kw))
        return SimpleNamespace(message_id=1)


@pytest.fixture()
def no_duplicates(monkeypatch):
    from app.bot import notifier

    released: list[int] = []

    async def fresh(chat_id, listing):  # noqa: ANN001
        return False

    async def release(chat_id, listing):  # noqa: ANN001
        released.append(chat_id)

    monkeypatch.setattr(notifier, "_duplicate_send", fresh)
    monkeypatch.setattr(notifier, "_release_send_guard", release)
    return released


def _bad(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=None, message=message)


# --- Who gets a copy ------------------------------------------------------------------
def test_a_target_alone_is_not_enough_the_level_must_include_it():
    assert forwarding.target_for(_user(SubscriptionTier.UNLIMITED)) == CHANNEL
    # A Profi who downgraded keeps the choice; it simply is not in effect.
    assert forwarding.target_for(_user(SubscriptionTier.PRO)) is None
    assert forwarding.target_for(_user(SubscriptionTier.UNLIMITED, target=None)) is None


# --- Reading the target from what the user sent ---------------------------------------
def test_a_forwarded_post_names_its_channel():
    message = SimpleNamespace(
        forward_origin=SimpleNamespace(chat=SimpleNamespace(id=CHANNEL)), text=None
    )
    assert forwarding.parse_target(message) == CHANNEL


def test_names_links_and_ids_are_understood():
    assert forwarding.parse_target(SimpleNamespace(forward_origin=None, text="@deals_de")) == "@deals_de"
    assert forwarding.parse_target(SimpleNamespace(forward_origin=None, text="https://t.me/deals_de")) == "@deals_de"
    assert forwarding.parse_target(SimpleNamespace(forward_origin=None, text=str(CHANNEL))) == CHANNEL
    assert forwarding.parse_target(SimpleNamespace(forward_origin=None, text="hallo")) is None
    assert forwarding.parse_target(SimpleNamespace(forward_origin=None, text="")) is None


# --- Checking the bot can actually post there -----------------------------------------
def _chat(kind: str, title: str = "Deals") -> SimpleNamespace:
    return SimpleNamespace(id=CHANNEL, type=kind, title=title, username=None)


def test_a_channel_needs_the_bot_as_posting_admin():
    admin = SimpleNamespace(status="administrator", can_post_messages=True)
    ok = asyncio.run(forwarding.verify(FakeBot(chat=_chat("channel"), member=admin), "@deals"))
    assert ok.ok and ok.chat_id == CHANNEL and ok.title == "Deals"

    muted = SimpleNamespace(status="administrator", can_post_messages=False)
    assert asyncio.run(forwarding.verify(FakeBot(chat=_chat("channel"), member=muted), "@deals")).reason == "not_admin"

    member = SimpleNamespace(status="member")
    assert asyncio.run(forwarding.verify(FakeBot(chat=_chat("channel"), member=member), "@deals")).reason == "not_admin"


def test_a_group_only_needs_the_bot_inside():
    member = SimpleNamespace(status="member")
    assert asyncio.run(forwarding.verify(FakeBot(chat=_chat("supergroup"), member=member), CHANNEL)).ok


def test_private_chats_and_unknown_chats_are_refused():
    assert asyncio.run(forwarding.verify(FakeBot(chat=_chat("private")), CHANNEL)).reason == "private"
    assert asyncio.run(forwarding.verify(FakeBot(chat=_bad("chat not found")), "@nope")).reason == "not_found"


# --- The copy itself -------------------------------------------------------------------
def test_the_copy_carries_the_card_and_only_the_link(no_duplicates):
    bot = FakeBot()
    user = _user()
    sent = asyncio.run(forwarding.forward_card(bot, None, user, _listing(), "de"))
    assert sent is True
    kind, chat_id, text, kw = bot.sent[0]
    assert (kind, chat_id) == ("message", CHANNEL)
    assert "PS5 Slim" in text
    buttons = [b for row in kw["reply_markup"].inline_keyboard for b in row]
    assert len(buttons) == 1
    assert buttons[0].url == "https://example.com/777"
    assert buttons[0].callback_data is None


def test_a_photo_card_is_copied_as_a_photo(no_duplicates):
    bot = FakeBot()
    asyncio.run(forwarding.forward_card(bot, None, _user(), _listing(image="https://img/1.jpg"), "de"))
    assert bot.sent[0][0] == "photo"


def test_without_the_feature_nothing_leaves(no_duplicates):
    bot = FakeBot()
    sent = asyncio.run(forwarding.forward_card(bot, None, _user(SubscriptionTier.PRO), _listing(), "de"))
    assert sent is False and bot.sent == []


def test_the_channel_guard_stops_the_same_ad_twice(monkeypatch):
    from app.bot import notifier

    async def already(chat_id, listing):  # noqa: ANN001
        return True

    monkeypatch.setattr(notifier, "_duplicate_send", already)
    bot = FakeBot()
    assert asyncio.run(forwarding.forward_card(bot, None, _user(), _listing(), "de")) is False
    assert bot.sent == []


def test_a_lost_channel_is_forgotten_and_the_owner_told_once(no_duplicates):
    bot = FakeBot(fail=TelegramForbiddenError(method=None, message="bot was kicked"))
    user = _user()
    sent = asyncio.run(forwarding.forward_card(bot, None, user, _listing(), "de"))
    assert sent is False
    assert user.forward_chat_id is None
    # The one message that did go out is the notice to the owner.
    assert [(k, c) for k, c, *_ in bot.sent] == [("message", 42)]
    assert "Weiterleitung deaktiviert" in bot.sent[0][2]
    assert no_duplicates == [CHANNEL]     # the guard was given back


def test_a_missing_chat_counts_as_lost_too(no_duplicates):
    bot = FakeBot(fail=_bad("chat not found"))
    user = _user()
    asyncio.run(forwarding.forward_card(bot, None, user, _listing(), "de"))
    assert user.forward_chat_id is None


# --- Wired into delivery ---------------------------------------------------------------
def test_both_delivery_paths_forward_after_success():
    from app.bot import notifier

    assert "forward_card" in inspect.getsource(notifier.notify_user_about_listings)
    assert "forward_card" in inspect.getsource(notifier.send_listing_card)
