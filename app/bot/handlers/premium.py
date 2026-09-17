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

from app.bot.handlers.usage import upgrade_nudge
from app.bot.texts import feature_label, t
from app.config.settings import settings
from app.database.models import PlanType, SubscriptionTier, User
from app.services import coupons as coupon_svc
from app.services import entitlements as ent
from app.services import premium, quota
from app.services import referrals as referral_svc

router = Router(name="premium")


def _cancellable(sub) -> bool:
    """True if this subscription auto-renews via Stars and can be cancelled."""
    return (
        sub is not None
        and sub.payment_provider == "telegram_stars"
        and bool(sub.telegram_charge_id)
        and sub.payment_status != premium.CANCEL_AT_PERIOD_END
    )


def _endable(sub) -> bool:
    """True if a non-renewing premium (trial/grant/coupon) can be ended early.

    Nothing is charged for these, but users still want to be able to give the
    premium back — e.g. to test the free tier again.
    """
    return (
        sub is not None
        and not _cancellable(sub)
        and sub.payment_status != premium.CANCEL_AT_PERIOD_END
    )


def _billing_text(info, sub) -> str:
    """'Last charge / next charge' lines derived from the payment ledger."""
    if info is None or info.payments_count == 0 or info.last_charge_at is None:
        return ""
    lines = [
        f"\n\n💳 Letzte Abbuchung: <b>{info.last_charge_at:%d.%m.%Y}</b> "
        f"({info.last_amount_stars} ⭐)"
    ]
    if sub is not None and sub.payment_status == premium.CANCEL_AT_PERIOD_END:
        lines.append("🔄 Nächste Abbuchung: <b>keine</b> (gekündigt)")
    elif sub is not None and _cancellable(sub) and info.next_charge_at:
        lines.append(f"🔄 Nächste Abbuchung: <b>{info.next_charge_at:%d.%m.%Y}</b>")
    lines.append("📜 Alle Zahlungen: /payments")
    return "\n".join(lines)


def _status_text(user: User, sub, billing: str, lang: str) -> str:
    """Where the user stands today — before the comparison of all levels."""
    if user.is_paid_tier and sub is not None:
        if sub.payment_status == premium.CANCEL_AT_PERIOD_END:
            return (
                "💎 <b>Premium — gekündigt</b>\n\n"
                f"✅ Läuft noch bis: <b>{sub.subscription_end:%d.%m.%Y}</b>\n"
                "❌ Verlängert sich danach <b>nicht</b> mehr.\n\n"
                "Umentschieden? Nach Ablauf einfach neu buchen: /premium"
                + billing
            )
        renewal = (
            f"🔄 Verlängert sich automatisch "
            f"({settings.premium_price_stars} ⭐/Monat)"
            if _cancellable(sub)
            else "⏳ Läuft danach automatisch aus (keine Abbuchung)"
        )
        return (
            t("premium.active", lang) + "\n\n"
            + t("premium.active_until", lang, date=f"{sub.subscription_end:%d.%m.%Y}")
            + f"\n{renewal}"
            + billing
        )
    if user.is_paid_tier:
        return (
            f"💎 <b>Stufe {escape(user.tier_label)}</b> (vom Admin freigeschaltet).\n"
            "Viel Spaß!"
        )
    return t("premium.title", lang)


def _level_block(e: ent.Entitlements, current: bool, lang: str) -> list[str]:
    """One level of the comparison — every figure read from its entitlements."""
    if e.is_paid:
        plan = premium.plan_for_tier(e.tier)
        price = t(
            "premium.compare_price", lang,
            stars=plan.price_stars, eur=f"{plan.price_eur:.2f}",
        )
    else:
        price = t("premium.compare_free_price", lang)
    head = f"<b>{escape(e.label)}</b> — {price}"
    if current:
        head += t("premium.compare_current", lang)
    fast = (
        t("premium.compare_fast", lang,
          slots=e.fast_slots, minutes=e.interval_floor(fast=True) // 60)
        if e.fast_slots
        else t("premium.compare_fast_none", lang)
    )
    return [
        head,
        t("premium.compare_searches", lang,
          rules=e.max_rules, minutes=e.interval_floor(fast=False) // 60),
        fast,
        t("premium.compare_cards", lang,
          cards=ent.fmt_quota(e.daily_notifications, lang=lang),
          photos=ent.fmt_quota(e.photo_evals_per_month, lang=lang)),
        t("premium.compare_quick", lang,
          quick=ent.fmt_quota(e.quick_searches_per_day, lang=lang),
          history=ent.fmt_quota(e.history_days, " " + t("quota.unit.days", lang), lang=lang)),
        t("premium.compare_sites", lang,
          sites=ent.fmt_quota(e.max_sites_per_rule, lang=lang)),
    ]


def _comparison_text(user: User, lang: str) -> str:
    """All four levels, cheapest first, with what each one adds."""
    current = user.subscription.canonical
    blocks = [t("premium.compare_title", lang)]
    inherited: frozenset[str] = frozenset()
    for e in ent.all_tiers():
        lines = _level_block(e, e.tier is current, lang)
        added = e.features - inherited
        if added:
            lines.append(
                t("premium.compare_adds", lang,
                  features=", ".join(feature_label(f, lang) for f in sorted(added)))
            )
        inherited = e.features
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _premium_text(user: User, sub, billing: str = "", lang: str = "de",
                  nudge: str | None = None) -> str:
    parts = [_status_text(user, sub, billing, lang), _comparison_text(user, lang)]
    if not premium.dealer_on_sale():
        # Naming the gap beats a silently missing plan: users notice the hole.
        parts.append(
            t("premium.not_bookable", lang,
              plan=escape(premium.plan_for_tier(SubscriptionTier.UNLIMITED).label))
        )
    if nudge:
        parts.append(nudge)
    footer = [t("premium.cancel_anytime", lang)]
    if settings.trial_enabled and not user.is_paid_tier:
        footer.append(t("premium.try_free", lang, days=settings.trial_days))
    footer.append(t("premium.coupon_hint", lang))
    if settings.referral_enabled:
        footer.append(t("premium.referral_hint", lang))
    parts.append("\n".join(footer))
    text = "\n\n".join(parts)
    # Before the buy button, not after it: a withdrawal notice a customer only
    # finds once they have paid has not been given.
    if not user.is_paid_tier:
        text += _legal_note(lang)
    return text


def _legal_note(lang: str) -> str:
    """Point at the withdrawal notice before the buy button, not after.

    Shown only once the operator has configured one: a purchase hint that
    links to an empty page is worse than none.
    """
    from app.services import legal as legal_svc

    if not legal_svc.is_complete(for_sale=True):
        return ""
    return t("legal.before_purchase", lang)


async def _premium_keyboard(
    user: User,
    lang: str,
    *,
    price_stars: int | None = None,
    coupon_code: str | None = None,
    sub=None,
    has_payments: bool = False,
):
    kb = InlineKeyboardBuilder()
    if not user.is_paid_tier and settings.premium_enabled:
        if price_stars is not None:
            # Coupon flow: one discounted button for the flagship plan.
            link = await premium.create_invoice_link(
                price_stars=price_stars, coupon_code=coupon_code
            )
            if link:
                kb.row(
                    InlineKeyboardButton(
                        text=t(
                            "premium.btn_buy", lang, plan="Premium", stars=price_stars
                        ),
                        url=link,
                    )
                )
        else:
            for plan in premium.available_plans():
                link = await premium.create_invoice_link(plan_key=plan.key)
                if link:
                    kb.row(
                        InlineKeyboardButton(
                            text=t(
                                "premium.btn_buy", lang,
                                plan=plan.label, stars=plan.price_stars,
                            ),
                            url=link,
                        )
                    )
    if user.is_paid_tier and _cancellable(sub):
        kb.row(
            InlineKeyboardButton(
                text=t("premium.btn_cancel", lang), callback_data="premium:cancel"
            )
        )
    elif user.is_paid_tier and _endable(sub):
        kb.row(
            InlineKeyboardButton(
                text="❌ Premium beenden", callback_data="premium:end"
            )
        )
    if has_payments:
        kb.row(
            InlineKeyboardButton(
                text=t("premium.btn_history", lang), callback_data="premium:history"
            )
        )
    kb.row(
        InlineKeyboardButton(text=t("btn.usage", lang), callback_data="menu:usage")
    )
    kb.row(InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:home"))
    return kb.as_markup()


async def _premium_view(user: User, session: AsyncSession, lang: str):
    """Text + keyboard of the premium page, billing dates included."""
    sub = await premium.get_active_subscription(session, user.telegram_id)
    info = await premium.billing_info(session, user.telegram_id)
    has_payments = bool(await premium.payment_history(session, user.telegram_id, limit=1))
    nudge = upgrade_nudge(user, lang, await quota.snapshot(user))
    text = _premium_text(user, sub, _billing_text(info, sub), lang, nudge)
    markup = await _premium_keyboard(user, lang, sub=sub, has_payments=has_payments)
    return text, markup


@router.message(Command("premium"))
async def cmd_premium(
    message: Message, user: User, session: AsyncSession, lang: str
) -> None:
    text, markup = await _premium_view(user, session, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "menu:premium")
async def cb_premium(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    text, markup = await _premium_view(user, session, lang)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# --- Payment history (dates of every charge) --------------------------------------
_PROVIDER_LABEL = {
    "telegram_stars": "⭐ Stars",
    "admin_grant": "🎁 Geschenk (Admin)",
    "trial": "🆓 Test",
    "coupon": "🎟 Gutschein",
    "referral": "🎫 Empfehlung",
}


async def _history_text(session: AsyncSession, user: User) -> str:
    payments = await premium.payment_history(session, user.telegram_id, limit=12)
    if not payments:
        return "📜 <b>Zahlungsverlauf</b>\n\nNoch keine Zahlungen."
    info = await premium.billing_info(session, user.telegram_id)
    lines = ["📜 <b>Zahlungsverlauf</b>\n"]
    for p in payments:
        when = f"{p.created_at:%d.%m.%Y %H:%M}"
        label = _PROVIDER_LABEL.get(p.provider, p.provider)
        amount = f"{p.amount_stars} ⭐ (~{p.amount_eur:.2f} €)" if p.amount_stars else "0 €"
        kind = " · Verlängerung" if p.is_renewal else ""
        coupon = f" · 🎟 {p.coupon_code}" if p.coupon_code else ""
        state = " · ↩️ ERSTATTET" if p.refunded else ""
        lines.append(f"• <b>{when}</b> — {label}: {amount}{kind}{coupon}{state}")
    if info.next_charge_at and user.is_paid_tier:
        lines.append(f"\n🔄 Nächste geplante Abbuchung: <b>{info.next_charge_at:%d.%m.%Y}</b>")
    lines.append("\nStars-Abo verwalten: /premium")
    return "\n".join(lines)


@router.message(Command("payments", "zahlungen"))
async def cmd_payments(message: Message, user: User, session: AsyncSession) -> None:
    await message.answer(await _history_text(session, user))


@router.callback_query(F.data == "premium:history")
async def cb_history(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Zurück", callback_data="menu:premium")
    await cb.message.edit_text(
        await _history_text(session, user), reply_markup=kb.as_markup()
    )
    await cb.answer()


# --- Ending a non-renewing premium (trial / grant / coupon) -------------------
@router.callback_query(F.data == "premium:end")
async def cb_end_confirm(
    cb: CallbackQuery, user: User, session: AsyncSession
) -> None:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    if not _endable(sub):
        await cb.answer("Nichts zu beenden.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ja, Premium beenden", callback_data="premium:end_yes")
    kb.button(text="⬅️ Zurück", callback_data="menu:premium")
    kb.adjust(1)
    await cb.message.edit_text(
        "❌ <b>Premium beenden?</b>\n\n"
        "Dieses Premium wird nicht abgerechnet (Test/Geschenk/Gutschein) — "
        "du kannst es aber sofort beenden und im Free-Tarif weitermachen.\n\n"
        "Wirklich beenden?",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data == "premium:end_yes")
async def cb_end_do(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    if not _endable(sub):
        await cb.answer("Nichts zu beenden.", show_alert=True)
        return
    await premium.deactivate_premium(session, user)
    logger.info("PREMIUM: {} ended a non-renewing premium in-bot", user.telegram_id)
    await cb.message.edit_text(
        "✅ <b>Premium beendet.</b>\n\n"
        "Du bist wieder im Free-Tarif. Jederzeit zurück: /premium 💎"
    )
    await cb.answer("Premium beendet")


# --- In-bot cancellation ------------------------------------------------------
@router.callback_query(F.data == "premium:cancel")
async def cb_cancel_confirm(
    cb: CallbackQuery, user: User, session: AsyncSession
) -> None:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    if not _cancellable(sub):
        await cb.answer("Nichts zu kündigen.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ja, wirklich kündigen", callback_data="premium:cancel_yes")
    kb.button(text="⬅️ Zurück", callback_data="menu:premium")
    kb.adjust(1)
    await cb.message.edit_text(
        "❌ <b>Premium kündigen?</b>\n\n"
        f"Dein Premium bleibt bis <b>{sub.subscription_end:%d.%m.%Y}</b> voll "
        "aktiv — es wird danach nur nicht mehr verlängert und nichts mehr "
        "abgebucht.\n\nWirklich kündigen?",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data == "premium:cancel_yes")
async def cb_cancel_do(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    if not _cancellable(sub):
        await cb.answer("Nichts zu kündigen.", show_alert=True)
        return

    ok = await premium.cancel_stars_subscription(
        user.telegram_id, sub.telegram_charge_id
    )
    if not ok:
        await cb.message.edit_text(
            "⚠️ Die Kündigung über den Bot hat gerade nicht geklappt.\n\n"
            "Alternative (dauert 30 Sekunden): Telegram-Einstellungen → "
            "⭐ Meine Sterne → Abos → Deal Hunter Premium → Kündigen.\n\n"
            "Oder gleich nochmal versuchen: /premium",
        )
        await cb.answer()
        return

    sub.payment_status = premium.CANCEL_AT_PERIOD_END
    sub.renewal_date = None
    await session.flush()
    logger.info("PREMIUM: {} cancelled in-bot", user.telegram_id)
    await cb.message.edit_text(
        "✅ <b>Gekündigt.</b>\n\n"
        f"Dein Premium bleibt bis <b>{sub.subscription_end:%d.%m.%Y}</b> aktiv "
        "und verlängert sich danach nicht mehr — es wird nichts mehr "
        "abgebucht.\n\nSchade! Falls du zurückkommst: /premium 💎"
    )
    await cb.answer("Abo gekündigt")


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
        tier=premium.trial_tier(),
    )
    # Grants belong in the ledger too, otherwise /payments and the admin view
    # cannot explain where a premium came from.
    await premium.record_payment(
        session, user, provider="trial", subscription_id=sub.id, status="granted",
        invoice_payload=f"trial:{settings.trial_days}d",
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

    # Acquisition codes are for new customers: an active subscriber must not
    # stack free days or buy the next months at the newcomer discount.
    if user.is_paid_tier:
        await message.answer(
            "💎 Du hast bereits Premium — Gutscheine gelten nur für Neukunden.\n"
            "Verschenke den Code doch an jemanden, den du einladen willst. 🎁"
        )
        return

    if coupon.free_days:
        # Instant benefit: free premium days, counted immediately.
        sub = await premium.activate_premium(
            session, user, days=coupon.free_days,
            provider="coupon", plan=PlanType.COUPON,
        )
        await premium.record_payment(
            session, user, provider="coupon", subscription_id=sub.id,
            status="granted", coupon_code=code,
            invoice_payload=f"coupon:{coupon.free_days}d",
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
    # Payload: "premium_monthly[:<plan>][:<coupon>]" — older links carry the
    # coupon directly in the second field, so the plan lookup tolerates both.
    plan = premium.plan_for_payload(payload)
    parts = payload.split(":")
    coupon_code = parts[-1] if len(parts) > 1 and parts[-1] != plan.key else None
    charge_id = payment.telegram_payment_charge_id

    # Telegram may redeliver an update after a restart. One charge, one grant.
    if await premium.charge_already_processed(session, charge_id):
        logger.info("PREMIUM: duplicate charge {} ignored", charge_id)
        await message.answer("✅ Diese Zahlung ist bereits verbucht. Danke!")
        return

    # Renewal = the user already has paid charges on record.
    prior_payments = await premium.payments_count_for_user(session, user.telegram_id)

    sub = await premium.activate_premium(
        session,
        user,
        provider="telegram_stars",
        plan=PlanType.MONTHLY,
        charge_id=charge_id,
        price_stars=payment.total_amount,
        tier=plan.tier,
    )
    await premium.record_payment(
        session,
        user,
        provider="telegram_stars",
        amount_stars=payment.total_amount,
        # Book what was actually charged: a discounted (coupon) purchase must
        # not show up in the revenue report as a full-price sale.
        amount_eur=premium.stars_to_eur(payment.total_amount),
        charge_id=charge_id,
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
        f"🎉 <b>Willkommen bei {plan.label}!</b>\n\n"
        f"{plan.description}\n"
        "Status und Zahlungen jederzeit: /premium"
    )


@router.message(F.refunded_payment)
async def on_refunded_payment(
    message: Message, user: User, session: AsyncSession
) -> None:
    """Telegram refunded a Stars charge: book it and take the premium back."""
    refund = message.refunded_payment
    charge_id = getattr(refund, "telegram_payment_charge_id", None)
    if charge_id:
        await premium.mark_refunded(session, user.telegram_id, charge_id)
    await premium.deactivate_premium(session, user)
    logger.info("PREMIUM: refund for {} (charge {})", user.telegram_id, charge_id)
    await message.answer(
        "↩️ <b>Erstattung erhalten.</b> Dein Premium wurde beendet und die "
        "Zahlung im Verlauf als erstattet markiert (/payments)."
    )
