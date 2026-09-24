"""Copy every delivered deal card into a channel or group of the user's choice.

The Händler level was sold with "Weiterleitung in Kanäle": a dealer runs a
team, and the team reads a channel, not one person's chat. So a card that was
delivered to the owner is posted there too. It goes out AFTER the owner's own
delivery and never instead of it: the owner's chat is where the quota, the
audit row and the card's buttons live, and the channel copy is a plain
announcement with a link.

Two things decide whether a copy goes out at all: the user chose a target
(``users.forward_chat_id``) and their level still includes the feature. A
downgrade therefore silences the channel without touching the stored choice,
and an upgrade brings it back — the same rule the marketplace cap follows.

Losing the target — the bot removed from the channel, its posting right taken
away — is discovered on the next send. The choice is then cleared and the
owner told once, because a channel that silently stopped receiving cards is
the failure nobody notices for weeks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import format_deal_card, format_resale_line
from app.bot.texts import t
from app.database.models import Listing, User
from app.services import entitlements as ent

FEATURE = ent.FEATURE_FORWARDING

#: Chat types a copy may go to. A private chat is somebody's own dialogue with
#: the bot; the bot can only write there if they started it themselves.
ALLOWED_CHAT_TYPES = ("channel", "group", "supergroup")
_ADMIN_STATUSES = ("administrator", "creator")
_MEMBER_STATUSES = ("administrator", "creator", "member")
_CHAT_ID_RE = re.compile(r"^-?\d{5,}$")


def target_for(user: User) -> int | None:
    """Where this user's cards are copied to right now, if anywhere."""
    chat_id = getattr(user, "forward_chat_id", None)
    if not chat_id or not user.has_feature(FEATURE):
        return None
    return int(chat_id)


def parse_target(message: Message) -> int | str | None:
    """Read a channel from what the user sent: a forwarded post, or its name.

    A forwarded post carries the chat itself, which is the most reliable form
    and the one the instructions ask for. ``@name``, a ``t.me`` link and a raw
    numeric id are accepted as well, for people who know them.
    """
    origin = getattr(message, "forward_origin", None)
    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if chat is None:
        chat = getattr(message, "forward_from_chat", None)
    if chat is not None and getattr(chat, "id", None):
        return int(chat.id)

    text = (message.text or "").strip()
    if not text:
        return None
    link = re.match(r"^(?:https?://)?t\.me/([A-Za-z0-9_]{4,})/?", text)
    if link:
        return f"@{link.group(1)}"
    if text.startswith("@") and len(text) > 4:
        return text.split()[0]
    if _CHAT_ID_RE.match(text):
        return int(text)
    return None


@dataclass(slots=True)
class Verification:
    ok: bool
    #: "ok" | "not_found" | "private" | "not_admin"
    reason: str
    chat_id: int | None
    title: str


async def verify(bot: Bot, target: int | str) -> Verification:
    """Check that the bot can actually post in ``target`` before storing it."""
    try:
        chat = await bot.get_chat(target)
    except (TelegramBadRequest, TelegramForbiddenError):
        return Verification(False, "not_found", None, "")

    title = chat.title or (f"@{chat.username}" if chat.username else str(chat.id))
    chat_type = getattr(chat.type, "value", chat.type)
    if chat_type not in ALLOWED_CHAT_TYPES:
        return Verification(False, "private", chat.id, title)

    try:
        member = await bot.get_chat_member(chat.id, bot.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return Verification(False, "not_admin", chat.id, title)

    status = getattr(member, "status", "")
    status = getattr(status, "value", status)
    if chat_type == "channel":
        # In a channel only administrators post, and only those allowed to.
        can_post = getattr(member, "can_post_messages", True)
        ok = status in _ADMIN_STATUSES and can_post is not False
    else:
        ok = status in _MEMBER_STATUSES
    return Verification(ok, "ok" if ok else "not_admin", chat.id, title)


def link_only_keyboard(listing: Listing, lang: str) -> InlineKeyboardMarkup:
    """The channel copy carries the link and nothing else.

    The owner's buttons (favourite, ignore, negotiate) act on the owner's
    listing; pressed by a channel reader they would answer "not found" at
    best. A button that cannot work for the person seeing it is left off.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn.open_link", lang), url=listing.url)]]
    )


async def forward_card(
    bot: Bot, session: AsyncSession, user: User, listing: Listing, lang: str
) -> bool:
    """Post a copy of ``listing`` to the user's channel. True when one went out.

    Called after the owner's own delivery succeeded. Uses the same duplicate
    guard as every other send, keyed on the CHANNEL, so two dealers sharing a
    channel do not fill it with the same ad twice.
    """
    chat_id = target_for(user)
    if chat_id is None:
        return False

    from app.bot import notifier  # lazy: notifier imports this module

    if await notifier._duplicate_send(chat_id, listing):
        return False

    caption = format_deal_card(listing, lang)
    resale = format_resale_line(listing, lang)
    if resale:
        caption = f"{caption}\n\n{resale}"
    markup = link_only_keyboard(listing, lang)

    try:
        if listing.image_url:
            try:
                await bot.send_photo(chat_id, listing.image_url, caption=caption, reply_markup=markup)
                return True
            except TelegramBadRequest:
                pass  # image refused by Telegram: the text card still goes
        await bot.send_message(
            chat_id, caption, reply_markup=markup, disable_web_page_preview=False
        )
        return True
    except TelegramRetryAfter as exc:
        # Not worth holding a worker for: the owner has the card, the copy is
        # a courtesy. The guard is released so a later card is not blocked.
        logger.info("Flood wait {}s on forward to {} — copy skipped", exc.retry_after, chat_id)
        await notifier._release_send_guard(chat_id, listing)
        return False
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        await notifier._release_send_guard(chat_id, listing)
        await _drop_target(bot, user, chat_id, lang, reason=str(exc))
        return False
    except Exception as exc:  # noqa: BLE001 - a copy must never break a delivery
        logger.error("Forward to {} failed: {}", chat_id, exc)
        await notifier._release_send_guard(chat_id, listing)
        return False


async def _drop_target(bot: Bot, user: User, chat_id: int, lang: str, *, reason: str) -> None:
    """The channel is gone for us: forget it and tell the owner once."""
    logger.warning("Forwarding for user {} to {} dropped: {}", user.telegram_id, chat_id, reason)
    user.forward_chat_id = None
    try:
        await bot.send_message(
            user.telegram_id, t("forward.lost", lang, target=escape(str(chat_id)))
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not tell {} about the lost channel: {}", user.telegram_id, exc)
