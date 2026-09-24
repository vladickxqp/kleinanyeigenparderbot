"""Market report and CSV export — the two things a Profi rule was sold with.

Both sit on the rule page. Both are gated on the user's level at the moment
of the tap, not when the button was drawn: a button is a promise the handler
has to keep, and a user whose month ran out yesterday still sees it.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import feature_label, t
from app.database.models import User
from app.services import entitlements as ent
from app.services import export, market_report
from app.services.repositories import SearchRuleRepository

router = Router(name="reports")


def locked_text(feature: str, lang: str | None) -> str:
    """Which level unlocks ``feature`` — the honest answer to a locked tap."""
    level = ent.unlocks(feature)
    label = ent.TIER_LABELS[level] if level is not None else "—"
    return t("feature.locked", lang, feature=feature_label(feature, lang), level=label)


async def _rule(cb: CallbackQuery, session: AsyncSession, user: User, lang: str):
    rule_id = int(cb.data.split(":")[-1])
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        await cb.answer(t("edit.not_found", lang), show_alert=True)
    return rule


@router.callback_query(F.data.startswith("rule:report:"))
async def cb_report(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    if not user.has_feature(ent.FEATURE_MARKET_REPORT):
        await cb.answer(locked_text(ent.FEATURE_MARKET_REPORT, lang), show_alert=True)
        return
    rule = await _rule(cb, session, user, lang)
    if rule is None:
        return
    report = await market_report.build(session, rule)
    await cb.message.answer(
        market_report.render(report, lang), disable_web_page_preview=True
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rule:export:"))
async def cb_export(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    if not user.has_feature(ent.FEATURE_EXPORT):
        await cb.answer(locked_text(ent.FEATURE_EXPORT, lang), show_alert=True)
        return
    rule = await _rule(cb, session, user, lang)
    if rule is None:
        return
    rows = await export.rows_for_rule(session, rule.id, user.id)
    if not rows:
        await cb.answer(t("export.empty", lang), show_alert=True)
        return
    await cb.message.answer_document(
        BufferedInputFile(
            export.to_csv(rows, lang, include_rule=False),
            filename=export.filename(rule.name),
        ),
        caption=t("export.caption", lang, count=len(rows)),
    )
    await cb.answer()


@router.message(Command("export"))
async def cmd_export(
    message: Message, user: User, session: AsyncSession, lang: str
) -> None:
    """Every find across all rules, as one file."""
    if not user.has_feature(ent.FEATURE_EXPORT):
        await message.answer(locked_text(ent.FEATURE_EXPORT, lang))
        return
    rows = await export.rows_for_user(session, user.id)
    if not rows:
        await message.answer(t("export.empty", lang))
        return
    await message.answer_document(
        BufferedInputFile(
            export.to_csv(rows, lang, include_rule=True),
            filename=export.filename("alle"),
        ),
        caption=t("export.caption", lang, count=len(rows)),
    )
