"""/suche — ad-hoc search without creating a rule.

Runs the fast (non-browser) parsers once, applies the same relevance filter and
deal scoring as the pipeline, and answers with a compact result list. Nothing
is persisted. Each run costs one unit of the level's daily quota and is paced
by the level's cooldown — a quick search is real scrape load.
"""

from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.parsers import registry
from app.parsers.schemas import ParsedListing, SearchQuery
from app.services import quota
from app.services.deal_scorer import score_listing
from app.services.price_analysis import compute_price_stats
from app.services.relevance import filter_relevant
from app.services.throttle import manual_run_allowed

router = Router(name="quick_search")

MAX_RESULTS = 8


def _quota_footer(user: User, state: quota.QuotaState, lang: str) -> str:
    """The remaining searches, plus the way to get more once they run out."""
    if state.unlimited:
        return ""
    line = (
        f"\n🧮 Noch <b>{state.remaining}</b> von {state.limit} Schnell-Suchen "
        f"{state.window_label(lang)}."
    )
    if state.remaining == 0:
        hint = quota.upgrade_hint(quota.KIND_QUICK, user, lang)
        if hint:
            line += f"\nMehr davon: {hint}"
    return line


def _exhausted_text(user: User, state: quota.QuotaState, lang: str) -> str:
    lines = [
        f"🔍 Deine Schnell-Suchen sind {state.window_label(lang)} aufgebraucht "
        f"({state.used}/{state.limit}).",
        "Deine Dauer-Suchen laufen davon unberührt weiter: /menu",
    ]
    hint = quota.upgrade_hint(quota.KIND_QUICK, user, lang)
    if hint:
        lines.append(f"Mehr davon: {hint}")
    return "\n".join(lines)


@router.message(Command("suche"))
async def cmd_suche(
    message: Message, user: User, command: CommandObject, state: FSMContext,
    lang: str = "de",
) -> None:
    keywords = (command.args or "").strip()
    if not keywords:
        await message.answer(
            "🔍 <b>Schnell-Suche</b> — einmalig suchen, ohne Regel anzulegen.\n\n"
            "Nutzung: <code>/suche tesla model 3</code>"
        )
        return

    wait = await manual_run_allowed(
        user.telegram_id,
        user.entitlements.quick_search_cooldown_seconds,
        scope="quick",
    )
    if wait:
        await message.answer(
            f"⏳ Kurz durchatmen — noch {wait}s. "
            "Zu viele Suchen hintereinander riskieren eine Sperre der Marktplätze."
        )
        return

    # Checked before booking: consume() reports "exhausted" both when it refused
    # and when it handed out the last unit.
    before = await quota.check(quota.KIND_QUICK, user)
    if before.exhausted:
        await message.answer(_exhausted_text(user, before, lang))
        return
    usage = await quota.consume(quota.KIND_QUICK, user)
    if not usage.unlimited and usage.used <= before.used:
        # Another request took the last unit between the check and the booking.
        await message.answer(_exhausted_text(user, usage, lang))
        return

    status = await message.answer(f"🔍 Suche nach <b>{escape(keywords)}</b> läuft…")

    query = SearchQuery(keywords=keywords[:256], max_results=25)
    # Browser parsers (Playwright) are too slow for an interactive command.
    parsers = [p for p in registry if not p.requires_browser]
    results = await asyncio.gather(
        *(p.collect(query) for p in parsers), return_exceptions=True
    )
    parsed: list[ParsedListing] = []
    failures = 0
    for res in results:
        if isinstance(res, BaseException):
            failures += 1
        else:
            parsed.extend(res)

    if parsers and failures == len(parsers):
        # Nobody searched anything — the user must not pay a unit for that.
        await quota.release(quota.KIND_QUICK, user)
        await status.edit_text(
            "⚠️ Die Marktplätze waren gerade nicht erreichbar. "
            "Versuch es in ein paar Minuten noch einmal — die Suche wurde dir "
            "nicht angerechnet."
        )
        return

    parsed = filter_relevant(query, parsed)
    if not parsed:
        await status.edit_text(
            f"😕 Nichts gefunden für <b>{escape(keywords)}</b>. "
            "Andere Suchbegriffe probieren?" + _quota_footer(user, usage, lang)
        )
        return

    stats = compute_price_stats([p.price for p in parsed if p.price is not None])
    scored = sorted(
        ((score_listing(item, stats), item) for item in parsed),
        key=lambda pair: pair[0].score,
        reverse=True,
    )[:MAX_RESULTS]

    lines = [
        f"🔍 <b>{escape(keywords)}</b> — "
        f"{len(parsed)} Treffer"
        + (f", Marktpreis ~ {stats.median:,.0f} €".replace(",", ".") if stats.median else "")
        + ":\n"
    ]
    for deal, item in scored:
        price = f"{item.price:,.0f} €".replace(",", ".") if item.price else "—"
        meta: list[str] = [price, f"Score {deal.score}"]
        if item.location:
            meta.append(escape(item.location))
        lines.append(
            # Parsers hand back a pydantic Url; escape() only speaks str.
            f"• <a href=\"{escape(str(item.url), quote=True)}\">"
            f"{escape(item.title[:70])}</a>\n"
            f"   {'  ·  '.join(meta)}"
        )
    lines.append("\n💡 Dauerhaft überwachen? Ein Tipp auf den Knopf genügt.")
    footer = _quota_footer(user, usage, lang)
    if footer:
        lines.append(footer)

    # Remember the query so the button below can turn it into a real rule.
    await state.update_data(qs_keywords=keywords[:256])
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Als Dauer-Suche speichern", callback_data="qs:save")
    await status.edit_text(
        "\n".join(lines), disable_web_page_preview=True, reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "qs:save")
async def cb_save_as_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    """Turn the last quick search into a monitored rule in one tap.

    The wizard asks eight questions before showing anything; a user who just
    saw good results should not have to answer them again. Defaults are used
    and the edit menu opens right away for fine-tuning.
    """
    from app.bot.keyboards import rule_edit_keyboard
    from app.bot.texts import t
    from app.config.settings import settings
    from app.database.models import SearchRule
    from app.services.repositories import SearchRuleRepository

    data = await state.get_data()
    keywords = (data.get("qs_keywords") or "").strip()
    if not keywords:
        await cb.answer("Bitte /suche erneut ausführen.", show_alert=True)
        return

    repo = SearchRuleRepository(session)
    count = await repo.count_for_user(user.id)
    if user.telegram_id not in settings.admin_ids and count >= user.max_rules:
        await cb.answer(t("rule.limit_reached", lang, max=user.max_rules), show_alert=True)
        return

    rule = await repo.add(
        SearchRule(
            user_id=user.id,
            name=keywords[:128],
            keywords=keywords,
            interval_seconds=max(user.min_interval_seconds, 300),
        )
    )
    await state.clear()
    await cb.message.answer(
        f"✅ <b>{escape(rule.name)}</b> wird jetzt dauerhaft überwacht.\n\n"
        "Feintuning (Preis, Ort, Kategorie, Intervall) direkt hier:",
        reply_markup=rule_edit_keyboard(rule, lang),
    )
    await cb.answer("✅ Gespeichert")
