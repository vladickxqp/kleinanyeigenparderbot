"""Flip tracker: log purchases from deal cards, close them with a sale price,
see real profit statistics and switch on the flip-only delivery mode.

Flows:
  card 🛒 → ask purchase price (Enter/"ok" = listing price) → flip in inventory
  /flips  → inventory with ✅ Verkauft / ✖️ per item, 📈 profit, 🎯 flip mode
  ✅      → ask sale price → fees + net profit computed, stats updated
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import t
from app.database.models import Listing, User
from app.services import flips as flip_svc
from app.services.formatting_helpers import money
from app.services.parsing import parse_price_range

router = Router(name="flips")

#: Flip-mode presets offered in the menu (EUR net profit per item).
FLIP_MODE_PRESETS: list[int] = [20, 50, 100, 200]


class FlipState(StatesGroup):
    buy_price = State()
    sell_price = State()


def _parse_amount(text: str) -> float | None:
    """Single amount from user input ('450', '1.200 €', '450,50')."""
    parsed = parse_price_range(text)
    if parsed is None:
        return None
    value = parsed[1] if parsed[1] is not None else parsed[0]
    return value if value and value > 0 else None


# --- Purchase (from a deal card) ------------------------------------------------------
@router.callback_query(F.data.startswith("listing:buy:"))
async def cb_buy(
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    from app.services.repositories import ListingRepository

    listing = await ListingRepository(session).get_for_user(
        int(cb.data.split(":")[-1]), user.id
    )
    if listing is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    await state.set_state(FlipState.buy_price)
    await state.update_data(flip_listing_id=listing.id)
    suggested = money(listing.price) if listing.price else "—"
    await cb.message.answer(
        f"🛒 <b>{escape(listing.title[:80])}</b>\n\n"
        f"Für wie viel hast du gekauft? Angebotspreis: <b>{suggested}</b>\n"
        "Zahl senden — oder <code>ok</code>, wenn du zum Angebotspreis gekauft hast.\n"
        "(/cancel zum Abbrechen)"
    )
    await cb.answer()


@router.message(FlipState.buy_price, Command("cancel"))
@router.message(FlipState.sell_price, Command("cancel"))
async def cmd_flip_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✖️ Abgebrochen.")


@router.message(FlipState.buy_price, F.text)
async def flip_buy_price(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    from app.services.repositories import ListingRepository

    data = await state.get_data()
    listing = await ListingRepository(session).get_for_user(
        int(data.get("flip_listing_id", 0)), user.id
    )
    if listing is None:
        await state.clear()
        await message.answer("⚠️ Angebot nicht mehr gefunden.")
        return

    raw = (message.text or "").strip().lower()
    price = listing.price if raw in ("ok", "ja", "passt") else _parse_amount(raw)
    if price is None:
        await message.answer("⚠️ Bitte einen Betrag senden, z. B. <code>450</code>.")
        return

    await state.clear()
    flip = await flip_svc.record_purchase(session, user.telegram_id, listing, price)
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    est = ""
    if listing.estimated_market_price:
        net = flip_svc.estimated_net_profit(price, listing.estimated_market_price)
        est = (
            f"\n📈 Erwarteter Netto-Gewinn beim Verkauf zum Marktpreis "
            f"({money(listing.estimated_market_price)}): <b>{money(net)}</b>"
        )
    await message.answer(
        f"✅ Gekauft für <b>{money(flip.buy_price)}</b> — im Lager.{est}\n\n"
        f"📦 Offen: {stats.open_count} Flip(s), investiert {money(stats.invested_open)}\n"
        "Verkauft? → /flips → ✅ Verkauft"
    )


# --- Inventory --------------------------------------------------------------------------
async def _inventory_view(session: AsyncSession, user: User, lang: str):
    open_items = await flip_svc.open_flips(session, user.telegram_id)
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    min_net = await flip_svc.get_flip_min(user.telegram_id)

    mode = f"≥ {money(min_net)} Netto" if min_net else "aus"
    lines = [
        "📦 <b>Meine Flips</b>\n",
        f"🎯 Flip-Modus: <b>{mode}</b>",
        f"💰 Realisierter Gewinn: <b>{money(stats.net_profit)}</b> "
        f"({stats.sold_count} verkauft) · 30 Tage: {money(stats.net_last_30d)}",
        f"📦 Im Lager: <b>{stats.open_count}</b> · investiert {money(stats.invested_open)}",
    ]
    kb = InlineKeyboardBuilder()
    if open_items:
        lines.append("\n<b>Im Lager:</b>")
        for flip in open_items[:10]:
            lines.append(
                f"• <b>{escape(flip.title[:50])}</b> — gekauft {money(flip.buy_price)} "
                f"({flip.bought_at:%d.%m.})"
            )
            kb.row(
                InlineKeyboardButton(
                    text=f"✅ Verkauft: {flip.title[:22]}…" if len(flip.title) > 22
                    else f"✅ Verkauft: {flip.title}",
                    callback_data=f"flip:sell:{flip.id}",
                ),
                InlineKeyboardButton(text="✖️", callback_data=f"flip:cancel:{flip.id}"),
            )
    else:
        lines.append("\nNoch nichts im Lager. Auf einer Deal-Karte 🛒 drücken.")
    kb.row(
        InlineKeyboardButton(text="📈 Gewinn-Statistik", callback_data="flip:profit"),
        InlineKeyboardButton(text="🎯 Flip-Modus", callback_data="flip:mode"),
    )
    kb.row(InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:home"))
    return "\n".join(lines), kb.as_markup()


@router.message(Command("flips"))
async def cmd_flips(message: Message, user: User, session: AsyncSession, lang: str) -> None:
    text, markup = await _inventory_view(session, user, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "menu:flips")
async def cb_flips(cb: CallbackQuery, user: User, session: AsyncSession, lang: str) -> None:
    text, markup = await _inventory_view(session, user, lang)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# --- Sale ---------------------------------------------------------------------------------
@router.callback_query(F.data.startswith("flip:sell:"))
async def cb_sell(
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    flip = await flip_svc.get_flip(session, int(cb.data.split(":")[-1]), user.telegram_id)
    if flip is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    await state.set_state(FlipState.sell_price)
    await state.update_data(flip_id=flip.id)
    await cb.message.answer(
        f"💸 <b>{escape(flip.title[:80])}</b>\n"
        f"Gekauft für {money(flip.buy_price)}. Für wie viel verkauft?\n"
        "(/cancel zum Abbrechen)"
    )
    await cb.answer()


@router.message(FlipState.sell_price, F.text)
async def flip_sell_price(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    flip = await flip_svc.get_flip(session, int(data.get("flip_id", 0)), user.telegram_id)
    if flip is None:
        await state.clear()
        await message.answer("⚠️ Flip nicht mehr gefunden.")
        return
    price = _parse_amount(message.text or "")
    if price is None:
        await message.answer("⚠️ Bitte einen Betrag senden, z. B. <code>650</code>.")
        return

    await state.clear()
    flip = await flip_svc.record_sale(session, flip, price)
    net = flip.net_profit or 0.0
    roi = net / flip.buy_price * 100 if flip.buy_price else 0.0
    icon = "🎉" if net > 0 else "😬"
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    await message.answer(
        f"{icon} <b>Verkauft für {money(flip.sell_price)}</b>\n\n"
        f"Einkauf {money(flip.buy_price)} · Gebühren+Versand {money(flip.fees_eur)}\n"
        f"💰 Netto-Gewinn: <b>{money(net)}</b> (ROI {roi:+.0f}%)\n\n"
        f"📈 Gesamt realisiert: <b>{money(stats.net_profit)}</b> "
        f"aus {stats.sold_count} Flip(s)"
    )


@router.callback_query(F.data.startswith("flip:cancel:"))
async def cb_cancel_flip(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    flip = await flip_svc.get_flip(session, int(cb.data.split(":")[-1]), user.telegram_id)
    if flip is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    await flip_svc.cancel_flip(session, flip)
    text, markup = await _inventory_view(session, user, lang)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer("✖️ Entfernt")


# --- Statistics ---------------------------------------------------------------------------
async def _profit_text(session: AsyncSession, user: User) -> str:
    s = await flip_svc.profit_stats(session, user.telegram_id)
    if s.sold_count == 0 and s.open_count == 0:
        return (
            "📈 <b>Gewinn-Statistik</b>\n\n"
            "Noch keine Flips. Auf einer Deal-Karte 🛒 drücken, wenn du kaufst — "
            "ab dann rechnet der Bot deinen echten Gewinn mit."
        )
    lines = [
        "📈 <b>Gewinn-Statistik</b>\n",
        f"💰 Netto-Gewinn gesamt: <b>{money(s.net_profit)}</b>",
        f"📅 Letzte 30 Tage: <b>{money(s.net_last_30d)}</b>",
        f"🛒 Verkauft: {s.sold_count} · Umsatz {money(s.revenue)} · Gebühren {money(s.fees)}",
    ]
    if s.avg_margin_pct is not None:
        lines.append(f"📊 Ø Marge auf Einkauf: <b>{s.avg_margin_pct:.0f}%</b>")
    if s.best_title:
        lines.append(f"🏆 Bester Flip: {escape(s.best_title[:50])} (+{money(s.best_net)})")
    lines.append(f"\n📦 Im Lager: {s.open_count} · gebunden {money(s.invested_open)}")
    return "\n".join(lines)


@router.message(Command("profit"))
async def cmd_profit(message: Message, user: User, session: AsyncSession) -> None:
    await message.answer(await _profit_text(session, user))


@router.callback_query(F.data == "flip:profit")
async def cb_profit(cb: CallbackQuery, user: User, session: AsyncSession, lang: str) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Zu den Flips", callback_data="menu:flips")
    await cb.message.edit_text(await _profit_text(session, user), reply_markup=kb.as_markup())
    await cb.answer()


# --- Flip-only mode --------------------------------------------------------------------------
@router.callback_query(F.data == "flip:mode")
async def cb_flip_mode(cb: CallbackQuery, user: User) -> None:
    current = await flip_svc.get_flip_min(user.telegram_id)
    kb = InlineKeyboardBuilder()
    for preset in FLIP_MODE_PRESETS:
        mark = "✅ " if current == preset else ""
        kb.button(text=f"{mark}≥ {preset} €", callback_data=f"flip:mode:{preset}")
    kb.button(
        text=("✅ " if not current else "") + "Aus (alles zeigen)",
        callback_data="flip:mode:0",
    )
    kb.adjust(2, 2, 1)
    kb.row(InlineKeyboardButton(text="⬅️ Zurück", callback_data="menu:flips"))
    await cb.message.edit_text(
        "🎯 <b>Flip-Modus</b>\n\n"
        "Nur Angebote liefern, deren <b>erwarteter Netto-Gewinn</b> "
        "(Marktpreis − Gebühren − Versand − Kaufpreis) mindestens so hoch ist:\n\n"
        "Alles andere wird still verworfen. Preisstürze zählen mit.",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("flip:mode:"))
async def cb_set_flip_mode(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    try:
        value = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    await flip_svc.set_flip_min(user.telegram_id, value if value > 0 else None)
    text, markup = await _inventory_view(session, user, lang)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer(f"🎯 Flip-Modus: {'≥ ' + str(value) + ' €' if value else 'aus'}")
