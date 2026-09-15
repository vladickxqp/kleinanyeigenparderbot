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

from app.config.settings import settings
from app.database.models import Flip, Listing, Payment, SearchRule, User

router = Router(name="privacy")

PRIVACY_TEXT = (
    "🔐 <b>Deine Daten</b>\n\n"
    "<b>Was gespeichert wird</b>\n"
    "• Telegram-ID, Name/Username, Sprache\n"
    "• Deine Suchen (Begriffe, Ort, Preisrahmen, Intervall)\n"
    "• Gefundene Anzeigen deiner Suchen samt Favoriten und Preisverlauf\n"
    "• Deine Flips (Kauf-/Verkaufspreis, Gewinn)\n"
    "• Zahlungen: Betrag, Datum, Zahlungs-ID von Telegram\n\n"
    "<b>Was NICHT gespeichert wird</b>\n"
    "• Keine Telefonnummer, keine Adresse, keine Zahlungsdaten — "
    "die Abwicklung läuft komplett bei Telegram\n\n"
    "<b>Fotos</b>\n"
    "Bilder für die Foto-Bewertung werden zur Erkennung an einen "
    "KI-Dienst übertragen und danach nicht dauerhaft gespeichert.\n\n"
    "<b>Deine Rechte</b>\n"
    "• /meinedaten — Export als JSON-Datei\n"
    "• /loeschen — alles endgültig löschen\n\n"
    "Fragen? /support"
)


@router.message(Command("privacy", "datenschutz"))
async def cmd_privacy(message: Message) -> None:
    await message.answer(PRIVACY_TEXT, disable_web_page_preview=True)


@router.message(Command("meinedaten", "mydata"))
async def cmd_export(message: Message, user: User, session: AsyncSession) -> None:
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
        BufferedInputFile(blob, filename=f"meine-daten-{user.telegram_id}.json"),
        caption="📦 Das ist alles, was über dich gespeichert ist.",
    )


@router.message(Command("loeschen", "delete_my_data"))
async def cmd_delete(message: Message) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Ja, alles löschen", callback_data="privacy:delete:confirm")
    kb.button(text="✖️ Abbrechen", callback_data="privacy:delete:cancel")
    kb.adjust(1)
    await message.answer(
        "🗑 <b>Alle Daten löschen?</b>\n\n"
        "Das entfernt endgültig: dein Profil, alle Suchen, alle gefundenen "
        "Anzeigen, Favoriten und Flips.\n\n"
        "⚠️ Ein laufendes Premium-Abo musst du <b>vorher</b> in Telegram "
        "kündigen — sonst läuft die Abbuchung weiter.\n"
        "ℹ️ Zahlungsbelege bleiben anonymisiert erhalten (gesetzliche "
        "Aufbewahrungspflicht), sie lassen sich dir dann nicht mehr zuordnen.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "privacy:delete:cancel")
async def cb_cancel(cb: CallbackQuery) -> None:
    await cb.message.edit_text("✅ Nichts gelöscht — alles bleibt wie es ist.")
    await cb.answer()


@router.callback_query(F.data == "privacy:delete:confirm")
async def cb_confirm(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
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
    await cb.message.edit_text(
        f"🗑 Erledigt, {name}. Alle deine Daten sind gelöscht.\n\n"
        "Mit /start kannst du jederzeit neu anfangen — dann wie ein "
        "komplett neuer Nutzer."
    )
    await cb.answer("Gelöscht")
    for admin_id in settings.admin_ids:
        try:
            await cb.bot.send_message(
                admin_id, f"🗑 Nutzer <code>{telegram_id}</code> hat sein Konto gelöscht."
            )
        except Exception:  # noqa: BLE001
            pass
