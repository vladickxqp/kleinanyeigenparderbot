"""Premium purchase flow (Telegram Stars) and /premium status page."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import t
from app.config.settings import settings
from app.database.models import PlanType, User
from app.services import premium

router = Router(name="premium")


def _premium_text(user: User, sub) -> str:
    if user.is_paid_tier and sub is not None:
        return (
            "💎 <b>Du bist Premium!</b>\n\n"
            f"✅ Aktiv bis: <b>{sub.subscription_end:%d.%m.%Y}</b>\n"
            f"🔄 Verlängert sich automatisch"
            f" ({settings.premium_price_stars} ⭐/Monat)\n\n"
            "Kündigen: Telegram-Einstellungen → Meine Sterne → Abos."
        )
    if user.is_paid_tier:
        return "💎 <b>Du hast Premium</b> (vom Admin freigeschaltet). Viel Spaß!"
    return (
        "💎 <b>Deal Hunter Premium</b>\n\n"
        f"Nur <b>{settings.premium_price_stars} ⭐</b> (~{settings.premium_price_eur:.2f} €) "
        "pro Monat — jederzeit kündbar:\n\n"
        "♾ <b>Unbegrenzte Suchen</b> "
        f"(Free: {settings.free_max_rules})\n"
        f"⚡ <b>Prüf-Intervall ab {settings.paid_min_interval_seconds // 60} min</b> "
        f"(Free: ab {settings.free_min_interval_seconds // 60} min)\n"
        "🚀 Prioritäts-Verarbeitung\n"
        "💎 Premium-Badge\n"
        "🔮 Alle künftigen Premium-Features"
    )


async def _premium_keyboard(user: User, lang: str):
    kb = InlineKeyboardBuilder()
    if not user.is_paid_tier and settings.premium_enabled:
        link = await premium.create_invoice_link()
        if link:
            kb.row(
                InlineKeyboardButton(
                    text=f"💳 Premium holen ({settings.premium_price_stars} ⭐/Monat)",
                    url=link,
                )
            )
    kb.row(InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:home"))
    return kb.as_markup()


@router.message(Command("premium"))
async def cmd_premium(
    message: Message, user: User, session: AsyncSession, lang: str
) -> None:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    await message.answer(
        _premium_text(user, sub), reply_markup=await _premium_keyboard(user, lang)
    )


@router.callback_query(F.data == "menu:premium")
async def cb_premium(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    await cb.message.edit_text(
        _premium_text(user, sub), reply_markup=await _premium_keyboard(user, lang)
    )
    await cb.answer()


# --- Payment pipeline --------------------------------------------------------
@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Telegram asks for final confirmation right before charging."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(
    message: Message, user: User, session: AsyncSession
) -> None:
    """First charge AND every automatic monthly renewal arrive here."""
    payment = message.successful_payment
    await premium.activate_premium(
        session,
        user,
        provider="telegram_stars",
        plan=PlanType.MONTHLY,
        charge_id=payment.telegram_payment_charge_id,
        price_stars=payment.total_amount,
    )
    await message.answer(
        "🎉 <b>Willkommen bei Premium!</b>\n\n"
        "♾ Unbegrenzte Suchen und das schnellste Prüf-Intervall sind jetzt "
        "freigeschaltet. Status jederzeit: /premium"
    )
