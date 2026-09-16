"""Actions on a deal card: favorite, negotiate, ignore, track price.

The negotiation helper is metered (Free gets a few per month, paid levels
negotiate without a cap); everything else here is free of charge.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Listing, PriceHistory, User
from app.services import quota
from app.services.repositories import ListingRepository

router = Router(name="listings")


def _nego_footer(state: quota.QuotaState, lang: str) -> str:
    """What is left after this suggestion (paid levels negotiate without a cap)."""
    if state.unlimited:
        return ""
    return (
        f"\n\n🧮 Noch <b>{state.remaining}</b> von {state.limit} Verhandlungen "
        f"{state.window_label(lang)}."
    )


def _nego_exhausted_text(user: User, state: quota.QuotaState, lang: str) -> str:
    lines = [
        f"🤝 <b>Verhandlungs-Hilfe</b> — dein Kontingent ist {state.window_label(lang)} "
        f"aufgebraucht ({state.used}/{state.limit}).",
    ]
    hint = quota.upgrade_hint(quota.KIND_NEGO, user, lang)
    lines.append(
        f"Unbegrenzt verhandeln: {hint}" if hint else "Nächsten Monat geht es weiter."
    )
    return "\n".join(lines)


async def _get(session: AsyncSession, listing_id: int, user: User) -> Listing | None:
    """Owner-scoped lookup: callback data alone never grants access."""
    return await ListingRepository(session).get_for_user(listing_id, user.id)


@router.callback_query(F.data.startswith("listing:fav:"))
async def cb_favorite(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    listing = await _get(session, int(cb.data.split(":")[-1]), user)
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    listing.is_favorite = not listing.is_favorite
    await session.flush()
    await cb.answer("⭐ Zu Favoriten" if listing.is_favorite else "Entfernt")


@router.callback_query(F.data.startswith("listing:nego:"))
async def cb_negotiate(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    """Suggest an opening offer and a copyable negotiation message."""
    from html import escape

    from app.services.negotiation import build_message, suggest_offer

    listing = await _get(session, int(cb.data.split(":")[-1]), user)
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    if listing.price is None or listing.price < 5:
        await cb.answer("Kein verhandelbarer Preis hinterlegt.", show_alert=True)
        return

    # Checked before booking: consume() reports "exhausted" both when it refused
    # and when it handed out the last unit.
    state = await quota.check(quota.KIND_NEGO, user)
    if state.exhausted:
        await cb.message.answer(_nego_exhausted_text(user, state, lang))
        await cb.answer()
        return
    state = await quota.consume(quota.KIND_NEGO, user)

    offer = suggest_offer(listing.price)
    message_text = build_message(listing.title, listing.price, offer)
    await cb.message.answer(
        "🤝 <b>Verhandlungs-Vorschlag</b>\n\n"
        f"Preis: {listing.price:,.0f} € → Dein Angebot: <b>{offer:,} €</b>\n\n"
        "Nachricht zum Kopieren (antippen):\n"
        f"<code>{escape(message_text)}</code>\n\n"
        f"🔗 Direkt zur Anzeige: {escape(listing.url)}".replace(",", ".")
        + _nego_footer(state, lang),
        disable_web_page_preview=True,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("listing:ignore:"))
async def cb_ignore(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    listing = await _get(session, int(cb.data.split(":")[-1]), user)
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    listing.is_ignored = True
    await session.flush()
    await cb.answer("🙈 Ignoriert")


@router.callback_query(F.data.startswith("listing:track:"))
async def cb_track(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    listing = await _get(session, int(cb.data.split(":")[-1]), user)
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    result = await session.execute(
        select(PriceHistory)
        .where(PriceHistory.listing_id == listing.id)
        .order_by(PriceHistory.observed_at.asc())
    )
    history = result.scalars().all()
    if not history:
        await cb.answer("Noch keine Preishistorie", show_alert=True)
        return
    lines = "\n".join(
        f"{h.observed_at:%d.%m %H:%M} — {h.price:.0f} €" for h in history[-10:]
    )
    await cb.answer(f"👁 Preisverlauf:\n{lines}", show_alert=True)
