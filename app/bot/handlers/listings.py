"""Actions on a deal card: favorite, ignore, track price."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Listing, PriceHistory

router = Router(name="listings")


async def _get(session: AsyncSession, listing_id: int) -> Listing | None:
    return await session.get(Listing, listing_id)


@router.callback_query(F.data.startswith("listing:fav:"))
async def cb_favorite(cb: CallbackQuery, session: AsyncSession) -> None:
    listing = await _get(session, int(cb.data.split(":")[-1]))
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    listing.is_favorite = not listing.is_favorite
    await session.flush()
    await cb.answer("⭐ Zu Favoriten" if listing.is_favorite else "Entfernt")


@router.callback_query(F.data.startswith("listing:ignore:"))
async def cb_ignore(cb: CallbackQuery, session: AsyncSession) -> None:
    listing = await _get(session, int(cb.data.split(":")[-1]))
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    listing.is_ignored = True
    await session.flush()
    await cb.answer("🙈 Ignoriert")


@router.callback_query(F.data.startswith("listing:track:"))
async def cb_track(cb: CallbackQuery, session: AsyncSession) -> None:
    listing = await _get(session, int(cb.data.split(":")[-1]))
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
