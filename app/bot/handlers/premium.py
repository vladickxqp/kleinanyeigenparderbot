"""Premium purchase flow (Telegram Stars), trial, coupons and referrals."""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import t
from app.config.settings import settings
from app.database.models import PlanType, User
from app.services import coupons as coupon_svc
from app.services import premium
from app.services import referrals as referral_svc

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
    lines = [
        "💎 <b>Deal Hunter Premium</b>\n",
        f"Nur <b>{settings.premium_price_stars} ⭐</b> (~{settings.premium_price_eur:.2f} €) "
        "pro Monat — jederzeit kündbar:\n",
        f"♾ <b>Unbegrenzte Suchen</b> (Free: {settings.free_max_rules})",
        f"⚡ <b>Prüf-Intervall ab {settings.paid_min_interval_seconds // 60} min</b> "
        f"(Free: ab {settings.free_min_interval_seconds // 60} min)",
        "🚀 Prioritäts-Verarbeitung",
        "💎 Premium-Badge",
    ]
    if settings.trial_enabled:
        lines.append(f"\n🆓 Kostenlos testen: /trial ({settings.trial_days} Tage)")
    lines.append("🎟 Gutschein? /coupon CODE")
    if settings.referral_enabled:
        lines.append("🎫 Freunde werben, Gratis-Tage kassieren: /ref")
    return "\n".join(lines)


async def _premium_keyboard(
    user: User,
    lang: str,
    *,
    price_stars: int | None = None,
    coupon_code: str | None = None,
):
    kb = InlineKeyboardBuilder()
    if not user.is_paid_tier and settings.premium_enabled:
        link = await premium.create_invoice_link(
            price_stars=price_stars, coupon_code=coupon_code
        )
        if link:
            shown = price_stars or settings.premium_price_stars
            kb.row(
                InlineKeyboardButton(
                    text=f"💳 Premium holen ({shown} ⭐/Monat)", url=link
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


# --- Free trial -----------------------------------------------------------------
@router.message(Command("trial"))
async def cmd_trial(message: Message, user: User, session: AsyncSession) -> None:
    if not settings.trial_enabled:
        await message.answer("🆓 Der Test-Zeitraum ist aktuell nicht verfügbar.")
        return
    if user.is_paid_tier:
        await message.answer("💎 Du hast doch schon Premium! 😄")
        return
    if await premium.has_used_trial(session, user.telegram_id):
        await message.answer(
            "🆓 Du hast deinen Test-Zeitraum schon genutzt.\n"
            "Weiter geht's mit /premium 💎"
        )
        return
    sub = await premium.activate_premium(
        session, user, days=settings.trial_days,
        provider="trial", plan=PlanType.TRIAL,
    )
    logger.info("TRIAL: {} started ({}d)", user.telegram_id, settings.trial_days)
    await message.answer(
        f"🎉 <b>{settings.trial_days} Tage Premium — geschenkt!</b>\n\n"
        f"Aktiv bis <b>{sub.subscription_end:%d.%m.%Y}</b>. "
        "Danach geht's automatisch im Free-Tarif weiter (keine Kosten). "
        "Gefällt's dir? /premium 💎"
    )


# --- Coupons ---------------------------------------------------------------------
@router.message(Command("coupon", "gutschein"))
async def cmd_coupon(
    message: Message,
    user: User,
    session: AsyncSession,
    lang: str,
    command: CommandObject,
) -> None:
    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("Nutzung: <code>/coupon DEINCODE</code>")
        return
    try:
        coupon = await coupon_svc.validate_coupon(session, code, user.telegram_id)
    except coupon_svc.CouponError as exc:
        await message.answer(f"😕 {exc}")
        return

    if coupon.free_days:
        # Instant benefit: free premium days, counted immediately.
        sub = await premium.activate_premium(
            session, user, days=coupon.free_days,
            provider="coupon", plan=PlanType.COUPON,
        )
        await coupon_svc.mark_redeemed(session, coupon, user.telegram_id)
        await message.answer(
            f"🎁 Code <b>{escape(code)}</b> eingelöst: "
            f"<b>{coupon.free_days} Tage Premium</b>! "
            f"Aktiv bis {sub.subscription_end:%d.%m.%Y}."
        )
        return

    # Discount benefit: build a discounted invoice; the redemption is booked
    # when the purchase actually succeeds (code travels in the payload).
    price = coupon_svc.discounted_price_stars(coupon)
    await message.answer(
        f"🎟 Code <b>{escape(code)}</b> gültig: Premium für "
        f"<b>{price} ⭐</b> statt {settings.premium_price_stars} ⭐ im ersten Monat!",
        reply_markup=await _premium_keyboard(
            user, lang, price_stars=price, coupon_code=code
        ),
    )


# --- Referral ---------------------------------------------------------------------
@router.message(Command("ref", "einladen"))
async def cmd_ref(message: Message, user: User) -> None:
    if not settings.referral_enabled:
        await message.answer("🎫 Das Empfehlungsprogramm ist aktuell nicht aktiv.")
        return
    me = await message.bot.get_me()
    link = referral_svc.build_referral_link(me.username, user.telegram_id)
    await message.answer(
        "🎫 <b>Freunde werben, Premium kassieren!</b>\n\n"
        f"Dein persönlicher Link:\n{link}\n\n"
        f"Für jeden geworbenen Freund, der Premium kauft, bekommst du "
        f"<b>{settings.referral_reward_days} Tage Premium gratis</b>."
    )


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
    payload = payment.invoice_payload or ""
    coupon_code = payload.split(":", 1)[1] if ":" in payload else None

    # Renewal = the user already has paid charges on record.
    prior_payments = await premium.payments_count_for_user(session, user.telegram_id)

    sub = await premium.activate_premium(
        session,
        user,
        provider="telegram_stars",
        plan=PlanType.MONTHLY,
        charge_id=payment.telegram_payment_charge_id,
        price_stars=payment.total_amount,
    )
    await premium.record_payment(
        session,
        user,
        provider="telegram_stars",
        amount_stars=payment.total_amount,
        amount_eur=settings.premium_price_eur,
        charge_id=payment.telegram_payment_charge_id,
        invoice_payload=payload,
        coupon_code=coupon_code,
        subscription_id=sub.id,
        is_renewal=prior_payments > 0,
    )

    # Book the coupon redemption now that money actually flowed.
    if coupon_code:
        try:
            coupon = await coupon_svc.validate_coupon(
                session, coupon_code, user.telegram_id
            )
            await coupon_svc.mark_redeemed(session, coupon, user.telegram_id)
        except coupon_svc.CouponError:
            pass  # e.g. already booked elsewhere — the payment still counts

    # Reward the inviter on the user's FIRST real payment.
    if prior_payments == 0:
        rewarded_tg = await referral_svc.reward_referrer_if_due(session, user)
        if rewarded_tg:
            try:
                await message.bot.send_message(
                    rewarded_tg,
                    "🎫 <b>Dein geworbener Freund hat Premium gekauft!</b>\n"
                    f"🎁 Belohnung: <b>{settings.referral_reward_days} Tage "
                    "Premium</b> wurden dir gutgeschrieben.",
                )
            except Exception:  # noqa: BLE001
                pass

    await message.answer(
        "🎉 <b>Willkommen bei Premium!</b>\n\n"
        "♾ Unbegrenzte Suchen und das schnellste Prüf-Intervall sind jetzt "
        "freigeschaltet. Status jederzeit: /premium"
    )
