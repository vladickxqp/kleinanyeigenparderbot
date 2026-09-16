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

#: "I paid the asking price" — accepted in every language the bot speaks, so
#: the shortcut the prompt advertises works for non-German readers too.
CONFIRM_WORDS = frozenset(
    {"ok", "okay", "ja", "passt", "yes", "yep", "да", "ок", "так"}
)


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
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    from app.services.repositories import ListingRepository

    listing = await ListingRepository(session).get_for_user(
        int(cb.data.split(":")[-1]), user.id
    )
    if listing is None:
        await cb.answer(t("flip.not_found", lang), show_alert=True)
        return
    await state.set_state(FlipState.buy_price)
    await state.update_data(flip_listing_id=listing.id)
    suggested = money(listing.price) if listing.price else "—"
    await cb.message.answer(
        t(
            "flip.ask_buy_price", lang,
            title=escape(listing.title[:80]), price=suggested,
        )
    )
    await cb.answer()


@router.message(FlipState.buy_price, Command("cancel"))
@router.message(FlipState.sell_price, Command("cancel"))
async def cmd_flip_cancel(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer("✖️ " + t("common.cancelled", lang))


@router.message(FlipState.buy_price, F.text)
async def flip_buy_price(
    message: Message, user: User, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    from app.services.repositories import ListingRepository

    data = await state.get_data()
    listing = await ListingRepository(session).get_for_user(
        int(data.get("flip_listing_id", 0)), user.id
    )
    if listing is None:
        await state.clear()
        await message.answer(t("flip.listing_gone", lang))
        return

    raw = (message.text or "").strip().lower()
    price = listing.price if raw in CONFIRM_WORDS else _parse_amount(raw)
    if price is None:
        await message.answer(t("flip.need_amount", lang, example="450"))
        return

    await state.clear()
    flip = await flip_svc.record_purchase(session, user.telegram_id, listing, price)
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    est = ""
    if listing.estimated_market_price:
        net = flip_svc.estimated_net_profit(price, listing.estimated_market_price)
        est = t(
            "flip.expected_net", lang,
            market=money(listing.estimated_market_price), net=money(net),
        )
    await message.answer(
        t(
            "flip.bought", lang,
            price=money(flip.buy_price), extra=est, open=stats.open_count,
            invested=money(stats.invested_open), sold=t("flip.sold_word", lang),
        )
    )


# --- Inventory --------------------------------------------------------------------------
def mode_label(min_net: float | None, lang: str) -> str:
    """"≥ 50 € net" / "off" — the flip-only threshold in words."""
    if not min_net:
        return t("flip.mode_off", lang)
    return t("flip.mode_min", lang, amount=money(min_net))


def inventory_text(open_items, stats, min_net: float | None, lang: str) -> str:
    """The /flips page. Pure: everything it needs is already loaded."""
    lines = [
        t("flip.title", lang) + "\n",
        t("flip.mode_line", lang, mode=mode_label(min_net, lang)),
        t(
            "flip.realised", lang,
            net=money(stats.net_profit), count=stats.sold_count,
            net30=money(stats.net_last_30d),
        ),
        t(
            "flip.in_stock", lang,
            count=stats.open_count, invested=money(stats.invested_open),
        ),
    ]
    if open_items:
        lines.append("\n" + t("flip.stock_header", lang))
        lines.extend(
            t(
                "flip.stock_row", lang,
                title=escape(flip.title[:50]), price=money(flip.buy_price),
                date=f"{flip.bought_at:%d.%m.}",
            )
            for flip in open_items[:10]
        )
    else:
        lines.append("\n" + t("flip.stock_empty", lang))
    return "\n".join(lines)


def _inventory_keyboard(open_items, lang: str):
    kb = InlineKeyboardBuilder()
    for flip in open_items[:10]:
        title = f"{flip.title[:22]}…" if len(flip.title) > 22 else flip.title
        kb.row(
            InlineKeyboardButton(
                text=t("flip.btn_sold", lang, title=title),
                callback_data=f"flip:sell:{flip.id}",
            ),
            InlineKeyboardButton(text="✖️", callback_data=f"flip:cancel:{flip.id}"),
        )
    kb.row(
        InlineKeyboardButton(text=t("flip.btn_profit", lang), callback_data="flip:profit"),
        InlineKeyboardButton(text=t("flip.btn_mode", lang), callback_data="flip:mode"),
    )
    kb.row(InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:home"))
    return kb.as_markup()


async def _inventory_view(session: AsyncSession, user: User, lang: str):
    open_items = await flip_svc.open_flips(session, user.telegram_id)
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    min_net = await flip_svc.get_flip_min(user.telegram_id)
    return (
        inventory_text(open_items, stats, min_net, lang),
        _inventory_keyboard(open_items, lang),
    )


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
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    flip = await flip_svc.get_flip(session, int(cb.data.split(":")[-1]), user.telegram_id)
    if flip is None:
        await cb.answer(t("flip.not_found", lang), show_alert=True)
        return
    await state.set_state(FlipState.sell_price)
    await state.update_data(flip_id=flip.id)
    await cb.message.answer(
        t(
            "flip.ask_sell_price", lang,
            title=escape(flip.title[:80]), price=money(flip.buy_price),
        )
    )
    await cb.answer()


@router.message(FlipState.sell_price, F.text)
async def flip_sell_price(
    message: Message, user: User, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    data = await state.get_data()
    flip = await flip_svc.get_flip(session, int(data.get("flip_id", 0)), user.telegram_id)
    if flip is None:
        await state.clear()
        await message.answer(t("flip.gone", lang))
        return
    price = _parse_amount(message.text or "")
    if price is None:
        await message.answer(t("flip.need_amount", lang, example="650"))
        return

    await state.clear()
    flip = await flip_svc.record_sale(session, flip, price)
    net = flip.net_profit or 0.0
    roi = net / flip.buy_price * 100 if flip.buy_price else 0.0
    icon = "🎉" if net > 0 else "😬"
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    await message.answer(
        t(
            "flip.sold_result", lang,
            icon=icon, price=money(flip.sell_price), buy=money(flip.buy_price),
            fees=money(flip.fees_eur), net=money(net), roi=f"{roi:+.0f}%",
            total=money(stats.net_profit), count=stats.sold_count,
        )
    )


@router.callback_query(F.data.startswith("flip:cancel:"))
async def cb_cancel_flip(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    flip = await flip_svc.get_flip(session, int(cb.data.split(":")[-1]), user.telegram_id)
    if flip is None:
        await cb.answer(t("flip.not_found", lang), show_alert=True)
        return
    await flip_svc.cancel_flip(session, flip)
    text, markup = await _inventory_view(session, user, lang)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer(t("flip.removed", lang))


# --- Statistics ---------------------------------------------------------------------------
def profit_text(stats, lang: str) -> str:
    """The /profit page. Pure, so every language can be rendered in a test."""
    if stats.sold_count == 0 and stats.open_count == 0:
        return t("flip.profit_title", lang) + "\n\n" + t("flip.profit_empty", lang)
    lines = [
        t("flip.profit_title", lang) + "\n",
        t("flip.profit_total", lang, net=money(stats.net_profit)),
        t("flip.profit_30d", lang, net=money(stats.net_last_30d)),
        t(
            "flip.profit_sold", lang,
            count=stats.sold_count, revenue=money(stats.revenue),
            fees=money(stats.fees),
        ),
    ]
    if stats.avg_margin_pct is not None:
        lines.append(
            t("flip.profit_margin", lang, percent=f"{stats.avg_margin_pct:.0f}")
        )
    if stats.best_title:
        lines.append(
            t(
                "flip.profit_best", lang,
                title=escape(stats.best_title[:50]), net=money(stats.best_net),
            )
        )
    lines.append(
        "\n" + t(
            "flip.profit_stock", lang,
            count=stats.open_count, invested=money(stats.invested_open),
        )
    )
    return "\n".join(lines)


async def _profit_text(session: AsyncSession, user: User, lang: str) -> str:
    return profit_text(await flip_svc.profit_stats(session, user.telegram_id), lang)


@router.message(Command("profit"))
async def cmd_profit(
    message: Message, user: User, session: AsyncSession, lang: str
) -> None:
    await message.answer(await _profit_text(session, user, lang))


@router.callback_query(F.data == "flip:profit")
async def cb_profit(cb: CallbackQuery, user: User, session: AsyncSession, lang: str) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("flip.btn_back_to_flips", lang), callback_data="menu:flips")
    await cb.message.edit_text(
        await _profit_text(session, user, lang), reply_markup=kb.as_markup()
    )
    await cb.answer()


# --- Flip-only mode --------------------------------------------------------------------------
def flip_mode_text(lang: str) -> str:
    """The 🎯 flip-mode explainer."""
    return t("flip.mode_title", lang) + "\n\n" + t("flip.mode_body", lang)


@router.callback_query(F.data == "flip:mode")
async def cb_flip_mode(cb: CallbackQuery, user: User, lang: str) -> None:
    current = await flip_svc.get_flip_min(user.telegram_id)
    kb = InlineKeyboardBuilder()
    for preset in FLIP_MODE_PRESETS:
        mark = "✅ " if current == preset else ""
        kb.button(text=f"{mark}≥ {preset} €", callback_data=f"flip:mode:{preset}")
    kb.button(
        text=("✅ " if not current else "") + t("flip.mode_btn_off", lang),
        callback_data="flip:mode:0",
    )
    kb.adjust(2, 2, 1)
    kb.row(
        InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:flips")
    )
    await cb.message.edit_text(flip_mode_text(lang), reply_markup=kb.as_markup())
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
    await cb.answer(
        t("flip.mode_set", lang, mode=mode_label(value or None, lang))
    )
