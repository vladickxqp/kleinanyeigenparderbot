"""Send deal notifications to users. Used by the Celery worker after a scrape.

Creates a short-lived Bot instance, sends each notable listing as a card (photo
with caption when an image is available, otherwise a text message) and marks the
listing as notified. Price history is recorded by the search service.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from loguru import logger

from app.bot.formatting import format_deal_card, format_resale_line
from app.bot.keyboards import listing_actions_keyboard
from app.config.settings import settings
from app.database.models import Listing, User
from app.database.session import session_scope


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
            for listing_id in listing_ids:
                listing = await session.get(Listing, listing_id)
                if listing is None or listing.is_ignored:
                    continue
                ok = await _send_one(bot, user_telegram_id, listing, lang)
                if ok:
                    listing.notified = True
                    sent += 1
    finally:
        await bot.session.close()

    logger.info("Sent {}/{} deal card(s) to {}", sent, len(listing_ids), user_telegram_id)
    return sent


async def send_listing_card(
    bot: Bot, chat_id: int, listing: Listing, lang: str = "de"
) -> bool:
    """Deliver a single deal card using an already-running Bot instance.

    Used by the in-chat "run now" action; the Celery path uses
    :func:`notify_user_about_listings` instead.
    """
    return await _send_one(bot, chat_id, listing, lang)


async def _count_sent() -> None:
    """Feed the daily 'cards sent' counter (never raises)."""
    try:
        from app.services import health  # lazy: avoid import cycles

        await health.record_card_sent()
    except Exception:  # noqa: BLE001
        pass


#: How long the per-user duplicate-send guard remembers an ad.
SENT_GUARD_TTL_SECONDS = 14 * 86400


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


async def _send_one(bot: Bot, chat_id: int, listing: Listing, lang: str) -> bool:
    if await _duplicate_send(chat_id, listing):
        # Report success so callers mark the row notified and never retry it.
        return True

    caption = format_deal_card(listing)
    resale = format_resale_line(listing)
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
                return True
            except TelegramBadRequest:
                # Image URL rejected by Telegram; fall back to text.
                pass
        await bot.send_message(
            chat_id, caption, reply_markup=markup, disable_web_page_preview=False
        )
        await _count_sent()
        return True
    except TelegramForbiddenError:
        # User blocked the bot: mark them inactive.
        logger.info("User {} blocked the bot", chat_id)
        async with session_scope() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(User).where(User.telegram_id == chat_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.is_active = False
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send card to {}: {}", chat_id, exc)
        return False
