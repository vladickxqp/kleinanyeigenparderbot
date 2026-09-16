"""Send deal notifications to users. Used by the Celery worker after a scrape.

Creates a short-lived Bot instance, sends each notable listing as a card (photo
with caption when an image is available, otherwise a text message) and marks the
listing as notified. Price history is recorded by the search service.

This module is the single delivery funnel, so it is also where the daily card
quota is enforced, where every delivery attempt is written to ``notifications``
for auditing, and where a capped user gets one named teaser per day — silence
is the worst possible answer from a deal bot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import format_deal_card, format_resale_line
from app.bot.keyboards import listing_actions_keyboard
from app.config.settings import settings
from app.database.models import (
    Listing,
    Notification,
    NotificationChannel,
    SearchRule,
    User,
)
from app.database.session import session_scope
from app.services import quota
from app.services.flips import estimated_net_profit
from app.services.formatting_helpers import money

#: How long the per-user duplicate-send guard remembers an ad.
SENT_GUARD_TTL_SECONDS = 14 * 86400
#: One cap teaser per user per day: inform once, never nag.
CAP_TEASER_COOLDOWN_SECONDS = 86400
#: Ad titles are scraped text; keep the teaser readable on a phone.
TEASER_TITLE_CHARS = 80
#: Rows scanned when picking the day's best withheld find. The count beside it
#: is an exact COUNT(*); this bound only keeps a pathological day (thousands of
#: matches) from loading the whole table to name one title.
TEASER_CANDIDATE_ROWS = 200
#: Width of ``notifications.title``.
AUDIT_TITLE_CHARS = 256
#: Upper bound for the error text stored on a failed delivery.
ERROR_TEXT_CHARS = 500
#: Audit reason for a delivery the duplicate guard swallowed. Stored in
#: ``notifications.error`` so "sent 3" and three rows in the log agree.
DUPLICATE_REASON = "duplicate: already delivered to this chat"


async def notify_user_about_listings(
    user_telegram_id: int, listing_ids: list[int], lang: str = "de"
) -> int:
    """Send cards for the given listing ids to a user. Returns count sent.

    During the user's quiet hours the cards are queued for the morning digest
    instead of being delivered immediately.
    """
    if not listing_ids:
        return 0

    from app.services import quiet  # lazy: avoid import cycles

    if await quiet.is_quiet_now(user_telegram_id):
        await quiet.queue_digest(user_telegram_id, listing_ids)
        return 0

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    sent = 0
    try:
        async with session_scope() as session:
            user = await _user_by_telegram_id(session, user_telegram_id)
            withheld: list[Listing] = []
            for listing_id in listing_ids:
                listing = await session.get(Listing, listing_id)
                if listing is None or listing.is_ignored:
                    continue

                if await _duplicate_send(user_telegram_id, listing):
                    # Invariant chosen here: ``sent`` counts cards that really
                    # went out, and every listing that reached the delivery step
                    # leaves exactly one audit row. A suppressed duplicate is
                    # therefore recorded as not-sent with a reason rather than
                    # counted as a delivery nobody can find in the log. Nothing
                    # left to deliver, but the row must never come back through
                    # the rescue sweep.
                    listing.notified = True
                    if user is not None:
                        _record_attempt(session, user, listing, DUPLICATE_REASON)
                    continue

                booked: quota.QuotaState | None = None
                if user is not None:
                    booked = await _claim_card_slot(user)
                    if booked is None:
                        listing.withheld = True
                        # flush_unnotified() hunts for notified=False, so a
                        # capped card would otherwise be re-queued for the rest
                        # of its life.
                        listing.notified = True
                        withheld.append(listing)
                        continue

                error = await _deliver(bot, user_telegram_id, listing, lang)
                if error is None:
                    listing.notified = True
                    listing.notified_at = datetime.now(timezone.utc)
                    # A card held back earlier and delivered now (e.g. after a
                    # price drop re-opened it) must stop counting as withheld.
                    listing.withheld = False
                    sent += 1
                else:
                    # The guard was claimed before the attempt; give it back so
                    # the rescue sweep can really retry this card.
                    await _release_send_guard(user_telegram_id, listing)
                    if user is not None and booked is not None:
                        # Refund the window the unit was actually booked in —
                        # a batch that starts at 23:59 finishes after midnight.
                        await quota.release(
                            quota.KIND_CARDS, user, stamp=booked.stamp
                        )
                if user is not None:
                    _record_attempt(session, user, listing, error)

            if withheld and user is not None:
                await _send_cap_teaser(bot, session, user, withheld, lang)
    finally:
        await bot.session.close()

    logger.info("Sent {}/{} deal card(s) to {}", sent, len(listing_ids), user_telegram_id)
    return sent


async def send_listing_card(
    bot: Bot,
    chat_id: int,
    listing: Listing,
    lang: str = "de",
    *,
    user: User | None = None,
    session: AsyncSession | None = None,
) -> bool:
    """Deliver a single deal card using an already-running Bot instance.

    Used by the in-chat "run now" action. Passing ``user`` routes the card
    through the same daily quota and audit trail as the Celery path — without
    it the button would be a way around the cap.

    The return value means "this row is settled, do not retry it", which a
    suppressed duplicate also is; the audit row carries what actually happened.
    """
    booked: quota.QuotaState | None = None
    if user is not None:
        booked = await _claim_card_slot(user)
        if booked is None:
            return False

    if await _duplicate_send(chat_id, listing):
        # Same invariant as the Celery path: nothing went out, so the audit row
        # says so — and the unit booked a moment ago goes straight back, since
        # here the quota is claimed before the guard is asked.
        if user is not None and booked is not None:
            await quota.release(quota.KIND_CARDS, user, stamp=booked.stamp)
        if user is not None and session is not None:
            _record_attempt(session, user, listing, DUPLICATE_REASON)
        return True

    error = await _deliver(bot, chat_id, listing, lang)
    if error is None:
        listing.notified_at = datetime.now(timezone.utc)
        listing.withheld = False
    else:
        await _release_send_guard(chat_id, listing)
        if user is not None and booked is not None:
            await quota.release(quota.KIND_CARDS, user, stamp=booked.stamp)
    if user is not None and session is not None:
        _record_attempt(session, user, listing, error)
    return error is None


# --- Quota ----------------------------------------------------------------------------
async def _claim_card_slot(user: User) -> quota.QuotaState | None:
    """Book one unit of the daily card quota. None = the cap is reached.

    ``consume`` refuses without booking once the cap is reached, and otherwise
    returns the state AFTER booking — so a refusal is recognised by the counter
    not having moved. Reading the decision off ``consume`` alone (rather than a
    check-then-consume pair) is what keeps two parallel workers from handing out
    the same last unit twice.

    The booked state is returned rather than a bool because a refund has to name
    the window it was booked in.
    """
    before = await quota.check(quota.KIND_CARDS, user)
    if before.metered and before.exhausted:
        return None
    after = await quota.consume(quota.KIND_CARDS, user)
    if not after.metered:
        # Redis is down, so nothing was counted and "the counter did not move"
        # no longer means "refused". Deliver: a metering outage must never turn
        # the bot silent, which is exactly what withholding every card would do.
        return after
    return after if after.unlimited or after.used > before.used else None


async def _user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


def _estimated_profit(listing: Listing) -> float | None:
    """Expected net profit of a flip, or None when the market price is unknown."""
    if listing.price is None or listing.estimated_market_price is None:
        return None
    return estimated_net_profit(listing.price, listing.estimated_market_price)


def _best_find(rows: list[Listing]) -> Listing | None:
    """The find worth naming: highest expected profit, deal score breaks ties."""
    return max(
        rows,
        key=lambda item: (_estimated_profit(item) or 0.0, item.deal_score),
        default=None,
    )


async def _withheld_today(
    session: AsyncSession, user_id: int
) -> tuple[int, Listing | None]:
    """The day's real figures: how much the cap swallowed, and the best of it.

    Both come from the whole day rather than from the batch in hand, because
    the teaser fires on the FIRST card over the limit — reporting that batch
    would tell the user "1 weiterer Treffer" while dozens more are withheld in
    silence for the next 23 hours.
    """
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # The rows were marked in this transaction; autoflush is off on this session.
    await session.flush()
    scope = (
        SearchRule.user_id == user_id,
        Listing.withheld.is_(True),
        Listing.created_at >= midnight,
    )
    total = await session.scalar(
        select(func.count(Listing.id))
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .where(*scope)
    )
    rows = (
        (
            await session.execute(
                select(Listing)
                .join(SearchRule, SearchRule.id == Listing.rule_id)
                .where(*scope)
                .order_by(Listing.deal_score.desc(), Listing.id.desc())
                .limit(TEASER_CANDIDATE_ROWS)
            )
        )
        .scalars()
        .all()
    )
    return int(total or 0), _best_find(list(rows))


def _cap_teaser_text(
    user: User, total: int, best: Listing | None, lang: str
) -> str:
    """The teaser body for the day's current figures (HTML)."""
    noun = "weiterer Treffer" if total == 1 else "weitere Treffer"
    headline = f"🔒 Tageslimit erreicht — {total} {noun} heute"
    if best is not None:
        # Scraped text goes into an HTML message: escape, then clip.
        detail = f"bester: <b>{escape(best.title[:TEASER_TITLE_CHARS])}</b>"
        profit = _estimated_profit(best)
        if profit is not None and profit > 0:
            detail += f", ca. +{money(profit)} netto"
        elif best.price is not None:
            detail += f", {money(best.price)}"
        headline += f", {detail}"
    lines = [f"{headline}."]
    hint = quota.upgrade_hint(quota.KIND_CARDS, user, lang)
    if hint:
        lines.append(f"Mehr Karten pro Tag: {hint}")
    return "\n".join(lines)


def _teaser_message_key(telegram_id: int) -> str:
    return f"captease:msg:{telegram_id}"


async def _teaser_message_id(telegram_id: int) -> int | None:
    """Id of today's teaser, if one is already sitting in the user's chat."""
    try:
        from app.services.health import _redis  # lazy: avoid import cycles

        async with _redis() as r:
            raw = await r.get(_teaser_message_key(telegram_id))
        return int(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - no id simply means "nothing to edit"
        logger.debug("Cap teaser id lookup for {} failed: {}", telegram_id, exc)
        return None


async def _remember_teaser_message(telegram_id: int, message_id: int) -> None:
    """Remember the teaser for the rest of the day so it can be kept current."""
    try:
        from app.services.health import _redis  # lazy: avoid import cycles

        async with _redis() as r:
            await r.set(
                _teaser_message_key(telegram_id),
                str(message_id),
                ex=CAP_TEASER_COOLDOWN_SECONDS,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Cap teaser id store for {} failed: {}", telegram_id, exc)


async def _send_cap_teaser(
    bot: Bot, session: AsyncSession, user: User, withheld: list[Listing], lang: str
) -> None:
    """Tell the user what the cap costs them today, and keep that number true.

    A user who receives nothing assumes the bot is broken and churns; a user who
    learns that the best withheld find was worth +85 € has a reason to upgrade.
    But the message fires on the first card over the limit, so its figures age
    out within minutes.

    Of the two workable shapes — edit the one message, or post a summary at a
    fixed hour — this edits. It needs no scheduler and no second delivery path
    (the numbers are already in hand at every overflow), it is right the moment
    it changes instead of hours later, and Telegram does not re-notify on an
    edit: the user is still alerted exactly once a day, in the place where they
    already read the bad news. A fixed evening slot would also strand the user
    who checks their phone at noon with no explanation for the silence.
    """
    if not settings.notification_cap_teaser_enabled:
        return

    total, best = await _withheld_today(session, user.id)
    # The query is the source of truth for the day, but it must never understate
    # the batch in hand (e.g. rows created before midnight, capped only now).
    total = max(total, len(withheld))
    if best is None:
        best = _best_find(withheld)
    text = _cap_teaser_text(user, total, best, lang)

    message_id = await _teaser_message_id(user.telegram_id)
    if message_id is not None:
        await _edit_cap_teaser(bot, user.telegram_id, message_id, text)
        return

    from app.services import throttle  # lazy: avoid import cycles

    if await throttle.cooldown(
        f"captease:{user.telegram_id}", CAP_TEASER_COOLDOWN_SECONDS
    ):
        # Cooldown burnt but no message id (Redis lost the key, or the send
        # failed): staying silent keeps the one-notification-a-day promise.
        return

    try:
        message = await bot.send_message(
            user.telegram_id, text, disable_web_page_preview=True
        )
    except Exception as exc:  # noqa: BLE001 - a failed teaser must not fail the batch
        logger.warning("Cap teaser to {} failed: {}", user.telegram_id, exc)
        return

    message_id = getattr(message, "message_id", None)
    if message_id is not None:
        await _remember_teaser_message(user.telegram_id, int(message_id))


async def _edit_cap_teaser(
    bot: Bot, telegram_id: int, message_id: int, text: str
) -> None:
    """Refresh today's teaser in place — an edit does not notify again."""
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=telegram_id,
            message_id=message_id,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        # "message is not modified" (nothing changed) or "message to edit not
        # found" (the user deleted it). Re-sending would nag; stay quiet.
        logger.debug("Cap teaser edit for {} skipped: {}", telegram_id, exc)
    except Exception as exc:  # noqa: BLE001 - a failed teaser must not fail the batch
        logger.warning("Cap teaser edit to {} failed: {}", telegram_id, exc)


# --- Auditing -------------------------------------------------------------------------
def _record_attempt(
    session: AsyncSession, user: User, listing: Listing, error: str | None
) -> None:
    """Write the delivery attempt to ``notifications`` (history + support)."""
    session.add(
        Notification(
            user_id=user.id,
            listing_id=listing.id,
            channel=NotificationChannel.TELEGRAM,
            title=listing.title[:AUDIT_TITLE_CHARS],
            is_sent=error is None,
            error=error,
        )
    )


async def _count_sent() -> None:
    """Feed the daily 'cards sent' counter (never raises)."""
    try:
        from app.services import health  # lazy: avoid import cycles

        await health.record_card_sent()
    except Exception:  # noqa: BLE001
        pass


# --- Delivery -------------------------------------------------------------------------
async def _duplicate_send(chat_id: int, listing: Listing) -> bool:
    """Atomic last-line duplicate guard (Redis), shared by ALL delivery paths.

    Two of the user's rules can match the same ad and run in parallel worker
    processes — the DB-level cross-rule check is not atomic, so both could
    decide to send. This guard keys on (user, site, ad id) and stores the last
    sent price: the same ad at the same price is delivered exactly once, while
    a real price change (drop card) still goes through. Fails open: if Redis
    is unavailable the card is sent normally.
    """
    try:
        from app.services.health import _redis  # lazy: avoid import cycles

        key = f"sent:{chat_id}:{listing.site.value}:{listing.external_id}"
        price_tag = f"{listing.price:.0f}" if listing.price is not None else "none"
        async with _redis() as r:
            # SET NX GET: atomically claim the key OR learn who claimed it.
            prev = await r.set(
                key, price_tag, nx=True, get=True, ex=SENT_GUARD_TTL_SECONDS
            )
            if prev is None:
                return False  # first delivery of this ad — claimed, send it
            if prev == price_tag:
                logger.info(
                    "Duplicate send blocked: {} already got {}:{} at {}",
                    chat_id, listing.site.value, listing.external_id, price_tag,
                )
                return True
            # Price changed (e.g. drop card): update and let it through.
            await r.set(key, price_tag, ex=SENT_GUARD_TTL_SECONDS)
            return False
    except Exception as exc:  # noqa: BLE001 - guard must never block delivery
        logger.debug("sent-guard unavailable: {}", exc)
        return False


async def _release_send_guard(chat_id: int, listing: Listing) -> None:
    """Hand the guard key back when the card never made it out.

    The guard is claimed BEFORE the send, which is what makes it atomic against
    two workers. Without this release a failed send would be remembered as
    delivered, so the rescue sweep's retry would be reported as a duplicate and
    the card would be lost for good.
    """
    try:
        from app.services.health import _redis  # lazy: avoid import cycles

        async with _redis() as r:
            await r.delete(f"sent:{chat_id}:{listing.site.value}:{listing.external_id}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("sent-guard release failed: {}", exc)


async def _send_one(bot: Bot, chat_id: int, listing: Listing, lang: str) -> bool:
    if await _duplicate_send(chat_id, listing):
        # Report success so callers mark the row notified and never retry it.
        return True
    error = await _deliver(bot, chat_id, listing, lang)
    if error is not None:
        await _release_send_guard(chat_id, listing)
    return error is None


async def _deliver(bot: Bot, chat_id: int, listing: Listing, lang: str) -> str | None:
    """Put one card on the wire. None on success, else the error for the audit row.

    The duplicate guard lives in the callers: it claims its Redis key on the
    first call, so asking it twice for the same ad would report a duplicate and
    drop a card that was never sent.
    """
    caption = format_deal_card(listing, lang)
    resale = format_resale_line(listing, lang)
    if resale:
        caption = f"{caption}\n\n{resale}"
    markup = listing_actions_keyboard(listing, lang)

    try:
        if listing.image_url:
            try:
                await bot.send_photo(
                    chat_id, listing.image_url, caption=caption, reply_markup=markup
                )
                await _count_sent()
                return None
            except TelegramBadRequest:
                # Image URL rejected by Telegram; fall back to text.
                pass
        await bot.send_message(
            chat_id, caption, reply_markup=markup, disable_web_page_preview=False
        )
        await _count_sent()
        return None
    except TelegramForbiddenError as exc:
        logger.info("User {} blocked the bot", chat_id)
        await _deactivate(chat_id)
        return _error_text(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send card to {}: {}", chat_id, exc)
        return _error_text(exc)


def _error_text(exc: BaseException) -> str:
    return (str(exc) or exc.__class__.__name__)[:ERROR_TEXT_CHARS]


async def _deactivate(chat_id: int) -> None:
    """Stop addressing a user who blocked the bot."""
    async with session_scope() as session:
        user = await _user_by_telegram_id(session, chat_id)
        if user:
            user.is_active = False
