"""Privacy: what is stored, and self-service deletion of everything.

Once strangers pay for this, GDPR articles 15/17/20 are not optional. A user
must be able to see what the bot knows, take it with them and have it erased
without the operator touching the database by hand.
"""

from __future__ import annotations

import json
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import t
from app.config.settings import settings
from app.database.models import Flip, Listing, Payment, SearchRule, User

router = Router(name="privacy")


def privacy_text(lang: str | None = None) -> str:
    """What the bot stores, in the reader's language."""
    return t("privacy.page", lang)


@router.message(Command("privacy", "datenschutz"))
async def cmd_privacy(message: Message, lang: str) -> None:
    await message.answer(privacy_text(lang), disable_web_page_preview=True)


@router.message(Command("meinedaten", "mydata"))
async def cmd_export(
    message: Message, user: User, session: AsyncSession, lang: str
) -> None:
    """Send everything stored about this user as one JSON file."""
    rules = (
        await session.execute(select(SearchRule).where(SearchRule.user_id == user.id))
    ).scalars().all()
    listings = (
        await session.execute(
            select(Listing)
            .join(SearchRule, SearchRule.id == Listing.rule_id)
            .where(SearchRule.user_id == user.id)
        )
    ).scalars().all()
    flips = (
        await session.execute(select(Flip).where(Flip.telegram_id == user.telegram_id))
    ).scalars().all()
    payments = (
        await session.execute(
            select(Payment).where(Payment.telegram_id == user.telegram_id)
        )
    ).scalars().all()

    def when(value) -> str | None:
        return value.isoformat() if value else None

    export = {
        "profile": {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "language": user.language_code,
            "tier": user.subscription.value,
            "registered_at": when(user.created_at),
        },
        "search_rules": [
            {
                "name": r.name, "keywords": r.keywords,
                "exclude": list(r.exclude_keywords or []),
                "category": r.category, "location": r.location,
                "zip_code": r.zip_code, "radius_km": r.max_distance_km,
                "min_price": r.min_price, "max_price": r.max_price,
                "interval_seconds": r.interval_seconds, "active": r.is_active,
                "created_at": when(r.created_at),
            }
            for r in rules
        ],
        "listings": [
            {
                "title": item.title, "price": item.price, "url": item.url,
                "site": item.site.value if item.site else None,
                "favorite": item.is_favorite, "score": item.deal_score,
                "found_at": when(item.created_at),
            }
            for item in listings
        ],
        "flips": [
            {
                "title": f.title, "buy_price": f.buy_price,
                "sell_price": f.sell_price, "net_profit": f.net_profit,
                "status": f.status.value if f.status else None,
                "created_at": when(f.created_at),
            }
            for f in flips
        ],
        "payments": [
            {
                "provider": p.provider, "amount_stars": p.amount_stars,
                "amount_eur": p.amount_eur, "status": p.status,
                "refunded": p.refunded, "charge_id": p.charge_id,
                "date": when(p.created_at),
            }
            for p in payments
        ],
    }
    blob = json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8")
    await message.answer_document(
        BufferedInputFile(
            blob,
            filename=t("privacy.export_filename", lang, id=user.telegram_id),
        ),
        caption=t("privacy.export_caption", lang),
    )


def delete_confirm_keyboard(lang: str | None = None):
    kb = InlineKeyboardBuilder()
    kb.button(
        text=t("privacy.btn_delete_all", lang), callback_data="privacy:delete:confirm"
    )
    kb.button(text=t("btn.cancel", lang), callback_data="privacy:delete:cancel")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("loeschen", "delete_my_data"))
async def cmd_delete(message: Message, lang: str) -> None:
    await message.answer(
        t("privacy.delete_confirm", lang),
        reply_markup=delete_confirm_keyboard(lang),
    )


@router.callback_query(F.data == "privacy:delete:cancel")
async def cb_cancel(cb: CallbackQuery, lang: str) -> None:
    await cb.message.edit_text(t("privacy.delete_aborted", lang))
    await cb.answer()


@router.callback_query(F.data == "privacy:delete:confirm")
async def cb_confirm(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    telegram_id = user.telegram_id
    name = escape(user.display_name)

    # Keep the financial ledger (legally required) but cut its personal link.
    payments = (
        await session.execute(
            select(Payment).where(Payment.telegram_id == telegram_id)
        )
    ).scalars().all()
    for payment in payments:
        payment.user_id = None

    flips = (
        await session.execute(select(Flip).where(Flip.telegram_id == telegram_id))
    ).scalars().all()
    for flip in flips:
        await session.delete(flip)

    # Rules cascade to listings, notifications and price history.
    await session.delete(user)
    await session.flush()

    logger.info("PRIVACY: {} deleted their account and data", telegram_id)
    await cb.message.edit_text(t("privacy.deleted", lang, name=name))
    await cb.answer(t("privacy.deleted_toast", lang))
    for admin_id in settings.admin_ids:
        try:
            # Staff-facing notice: German, like the rest of the admin area.
            await cb.bot.send_message(
                admin_id, f"🗑 Nutzer <code>{telegram_id}</code> hat sein Konto gelöscht."
            )
        except Exception:  # noqa: BLE001
            pass
