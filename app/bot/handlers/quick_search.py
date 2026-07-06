"""/suche — ad-hoc search without creating a rule.

Runs the fast (non-browser) parsers once, applies the same relevance filter and
deal scoring as the pipeline, and answers with a compact result list. Nothing
is persisted.
"""

from __future__ import annotations

import asyncio
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.parsers import registry
from app.parsers.schemas import ParsedListing, SearchQuery
from app.services.deal_scorer import score_listing
from app.services.price_analysis import compute_price_stats
from app.services.relevance import filter_relevant

router = Router(name="quick_search")

MAX_RESULTS = 8


@router.message(Command("suche"))
async def cmd_suche(message: Message, command: CommandObject) -> None:
    keywords = (command.args or "").strip()
    if not keywords:
        await message.answer(
            "🔍 <b>Schnell-Suche</b> — einmalig suchen, ohne Regel anzulegen.\n\n"
            "Nutzung: <code>/suche tesla model 3</code>"
        )
        return

    status = await message.answer(f"🔍 Suche nach <b>{escape(keywords)}</b> läuft…")

    query = SearchQuery(keywords=keywords[:256], max_results=25)
    # Browser parsers (Playwright) are too slow for an interactive command.
    parsers = [p for p in registry if not p.requires_browser]
    results = await asyncio.gather(
        *(p.collect(query) for p in parsers), return_exceptions=True
    )
    parsed: list[ParsedListing] = []
    for res in results:
        if not isinstance(res, BaseException):
            parsed.extend(res)

    parsed = filter_relevant(query, parsed)
    if not parsed:
        await status.edit_text(
            f"😕 Nichts gefunden für <b>{escape(keywords)}</b>. "
            "Andere Suchbegriffe probieren?"
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
            f"• <a href=\"{item.url}\">{escape(item.title[:70])}</a>\n"
            f"   {'  ·  '.join(meta)}"
        )
    lines.append("\n💡 Dauerhaft überwachen? ➕ Neue Suche im /menu anlegen.")

    await status.edit_text("\n".join(lines), disable_web_page_preview=True)
