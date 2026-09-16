"""Generic main-menu callback handlers (home, help, stats, favorites)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu_keyboard
from app.bot.texts import t
from app.database.models import Listing, SearchRule, User

router = Router(name="menu")


@router.callback_query(F.data.in_({"menu:home", "menu:back"}))
async def cb_home(cb: CallbackQuery, lang: str) -> None:
    await cb.message.edit_text(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))
    await cb.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(cb: CallbackQuery, lang: str) -> None:
    await cb.message.edit_text(
        t("help.body", lang) + "\n\n" + t("privacy.commands", lang),
        reply_markup=main_menu_keyboard(lang),
    )
    await cb.answer()


@router.callback_query(F.data == "menu:stats")
async def cb_stats(cb: CallbackQuery, user: User, session: AsyncSession, lang: str) -> None:
    rules_count = await session.scalar(
        select(func.count(SearchRule.id)).where(SearchRule.user_id == user.id)
    )
    listings_count = await session.scalar(
        select(func.count(Listing.id))
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .where(SearchRule.user_id == user.id)
    )
    text = (
        "📊 <b>Deine Statistik</b>\n\n"
        f"📋 Suchen: <b>{rules_count or 0}</b>\n"
        f"🛒 Gefundene Angebote: <b>{listings_count or 0}</b>\n"
        f"🏷 Abo: <b>{user.subscription.value}</b>"
    )
    await cb.message.edit_text(text, reply_markup=main_menu_keyboard(lang))
    await cb.answer()


@router.callback_query(F.data == "menu:favorites")
async def cb_favorites(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    result = await session.execute(
        select(Listing)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .where(SearchRule.user_id == user.id, Listing.is_favorite.is_(True))
        .order_by(Listing.deal_score.desc())
        .limit(10)
    )
    favs = result.scalars().all()
    if not favs:
        await cb.answer("⭐ Noch keine Favoriten", show_alert=True)
        return
    lines = ["⭐ <b>Favoriten</b>\n"]
    for fav in favs:
        price = f"{fav.price:.0f} €" if fav.price else "—"
        lines.append(f"• <a href='{fav.url}'>{fav.title[:60]}</a> — {price}")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=main_menu_keyboard(lang),
        disable_web_page_preview=True,
    )
    await cb.answer()
