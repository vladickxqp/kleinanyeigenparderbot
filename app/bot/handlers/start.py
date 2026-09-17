"""/start, /help and /status entrypoints."""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import language_keyboard, main_menu_keyboard
from app.bot.texts import t
from app.config.settings import settings
from app.database.models import Listing, SearchRule, User

router = Router(name="start")


def _is_new_user(user: User) -> bool:
    """True if the account was created within the last two minutes."""
    created = user.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() < 120


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    user: User,
    session: AsyncSession,
    lang: str,
    state: FSMContext,
    command: CommandObject,
) -> None:
    await state.clear()

    # Referral deep-link: /start ref<telegram_id> — only counts for NEW users.
    if _is_new_user(user):
        from app.services import referrals as referral_svc

        referrer_tg = referral_svc.parse_referral_payload(command.args)
        if referrer_tg:
            await referral_svc.register_referral(
                session, referrer_tg, user.telegram_id
            )

    await message.answer(t("start.greeting", lang))
    if _is_new_user(user):
        # First contact: let the user pick their language right away.
        await message.answer(t("settings.language", lang), reply_markup=language_keyboard())
    else:
        await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str) -> None:
    await message.answer(t("help.body", lang))


@router.message(Command("menu"))
async def cmd_menu(message: Message, lang: str, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


@router.message(Command("status"))
async def cmd_status(message: Message, user: User, session: AsyncSession, lang: str) -> None:
    """Live system status: is the worker searching, and what came in today?"""
    from app.services import health

    status = await health.get_status()

    active_rules = await session.scalar(
        select(func.count(SearchRule.id)).where(
            SearchRule.user_id == user.id, SearchRule.is_active.is_(True)
        )
    ) or 0
    day_ago = datetime.now(timezone.utc).timestamp() - 86400
    new_24h = await session.scalar(
        select(func.count(Listing.id))
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .where(
            SearchRule.user_id == user.id,
            Listing.created_at >= func.to_timestamp(day_ago),
        )
    ) or 0

    if status.worker_alive:
        worker_line = "🟢 Worker: läuft"
    elif status.last_dispatch_age is None:
        worker_line = "🔴 Worker: noch nie gelaufen — <code>docker compose ps</code> prüfen!"
    else:
        mins = int(status.last_dispatch_age // 60)
        worker_line = (
            f"🔴 Worker: seit {mins} min kein Lebenszeichen — "
            "<code>docker compose ps</code> prüfen!"
        )

    text = (
        "📊 <b>System-Status</b>\n\n"
        f"{worker_line}\n"
        f"🔄 Suchläufe heute (alle Nutzer): <b>{status.runs_today}</b>\n"
        f"📨 Karten gesendet heute: <b>{status.cards_sent_today}</b>\n\n"
        f"📋 Deine aktiven Suchen: <b>{active_rules}</b>\n"
        f"🆕 Deine neuen Angebote (24h): <b>{new_24h}</b>\n\n"
        "ℹ️ Suchläufe ohne Karten = es gab nichts wirklich Neues."
    )
    # Only the admins, and only while something is actually missing: going live
    # without an imprint and a withdrawal notice is the one mistake nobody
    # notices by looking at the product.
    if user.telegram_id in settings.admin_ids and settings.premium_enabled:
        from app.services import legal

        gaps = legal.missing(for_sale=True)
        if gaps:
            text += "\n\n" + t(
                "legal.admin_incomplete", lang, fields=", ".join(gaps)
            )
    await message.answer(text)
