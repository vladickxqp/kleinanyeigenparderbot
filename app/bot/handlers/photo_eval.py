"""Photo evaluation: send the bot a product photo, get a value estimate.

Flow: photo → Claude vision identifies the product → live Kleinanzeigen
comparables → market median + buy recommendation. Premium feature by default
(configurable); admins always have access. Only active outside FSM dialogs so
wizards are never hijacked by an accidental photo.
"""

from __future__ import annotations

import base64
import io
from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from loguru import logger

from app.config.settings import settings
from app.database.models import User
from app.parsers import registry
from app.parsers.schemas import SearchQuery
from app.services import vision
from app.services.formatting_helpers import money
from app.services.price_analysis import compute_price_stats
from app.services.relevance import filter_relevant

router = Router(name="photo_eval")


def _may_use_photo_eval(user: User) -> bool:
    if user.telegram_id in settings.admin_ids:
        return True
    if not settings.photo_ai_premium_only:
        return True
    return user.is_paid_tier


@router.message(StateFilter(None), F.photo)
async def on_photo(message: Message, user: User, lang: str) -> None:
    from app.services.ai import is_available

    if not is_available():
        hint = (
            "\n\n(Owner-Hinweis: ANTHROPIC_API_KEY + AI_ENABLED=true "
            "in der .env setzen.)"
            if user.telegram_id in settings.admin_ids
            else ""
        )
        await message.answer(
            "📸 Die Foto-Bewertung ist aktuell nicht aktiviert." + hint
        )
        return

    if not _may_use_photo_eval(user):
        await message.answer(
            "📸 <b>Foto-Bewertung</b> ist ein 💎 <b>Premium</b>-Feature:\n"
            "Schick ein Produktfoto → ich erkenne es und schätze den "
            "Marktwert mit Live-Vergleichspreisen.\n\nUpgrade: /premium"
        )
        return

    status = await message.answer("📸 Analysiere das Foto…")

    # Largest available resolution, capped by Telegram itself (~1280px).
    photo = message.photo[-1]
    buf = io.BytesIO()
    try:
        await message.bot.download(photo, destination=buf)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Photo download failed: {}", exc)
        await status.edit_text("⚠️ Konnte das Foto nicht laden — nochmal senden?")
        return

    image_b64 = base64.b64encode(buf.getvalue()).decode()
    result = await vision.assess_photo(image_b64, caption=message.caption)
    if result is None:
        await status.edit_text(
            "🤔 Ich konnte das Produkt nicht sicher erkennen. "
            "Tipp: näher ranzoomen, gutes Licht, oder Modellname als "
            "Bildunterschrift mitschicken."
        )
        return

    await status.edit_text(
        f"📸 Erkannt: <b>{escape(result.product)}</b>\n"
        "🔍 Hole Live-Vergleichspreise…"
    )

    # Live comparables from the fast parsers (Kleinanzeigen).
    query = SearchQuery(keywords=result.search_query, max_results=15)
    parsers = [p for p in registry if not p.requires_browser]
    comps = []
    for parser in parsers:
        comps.extend(await parser.collect(query))
    comps = filter_relevant(query, comps)
    stats = compute_price_stats([c.price for c in comps if c.price is not None])

    conf_badge = {"low": "🤷 unsicher", "medium": "👍 solide", "high": "🎯 sicher"}[
        result.confidence
    ]
    lines = [
        f"📸 <b>{escape(result.product)}</b>  ({conf_badge})\n",
    ]
    if result.est_value_eur:
        lines.append(f"🤖 KI-Schätzung: <b>~{money(result.est_value_eur)}</b>")
    if stats.has_data:
        lines.append(
            f"📊 Live auf Kleinanzeigen: <b>{money(stats.median)}</b> Median "
            f"({stats.count} Angebote, {money(stats.minimum)}–{money(stats.maximum)})"
        )
    market = stats.median if stats.has_data else result.est_value_eur
    if market:
        buy_below = market * 0.7
        lines.append(
            f"\n💡 <b>Zum Flippen kaufen unter ~{money(buy_below)}</b> "
            "(30% Marge vor Gebühren)"
        )
    if result.notes:
        lines.append(f"\n🔎 <i>{escape(result.notes)}</i>")

    # Top live comparables as links.
    top = sorted(
        (c for c in comps if c.price is not None), key=lambda c: c.price
    )[:3]
    if top:
        lines.append("\n<b>Günstigste Live-Angebote:</b>")
        for c in top:
            lines.append(
                f"• <a href=\"{c.url}\">{escape(c.title[:60])}</a> — {money(c.price)}"
            )
    lines.append("\n➕ Dauerhaft überwachen? /menu → Neue Suche")

    await status.edit_text("\n".join(lines), disable_web_page_preview=True)
