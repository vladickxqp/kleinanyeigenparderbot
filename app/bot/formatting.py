"""Render listings as pretty Telegram HTML deal cards."""

from __future__ import annotations

from html import escape

from app.database.models import Listing
from app.database.models.enums import DealVerdict

_VERDICT_BADGE: dict[DealVerdict, str] = {
    DealVerdict.STEAL: "🔥 <b>KRACHER</b>",
    DealVerdict.GREAT: "💚 <b>Top-Deal</b>",
    DealVerdict.GOOD: "✅ <b>Guter Deal</b>",
    DealVerdict.FAIR: "⚖️ Fairer Preis",
    DealVerdict.OVERPRICED: "🔴 Überteuert",
    DealVerdict.UNKNOWN: "❔ Unbewertet",
}


def _money(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "—"
    symbol = "€" if currency == "EUR" else currency
    return f"{value:,.0f} {symbol}".replace(",", ".")


def format_deal_card(listing: Listing) -> str:
    """Build the HTML caption for a deal notification card."""
    badge = _VERDICT_BADGE.get(listing.deal_verdict, "")
    # Title doubles as a clickable link so the offer is always one tap away,
    # in addition to the "Öffnen" button below the card.
    lines: list[str] = [
        f"{badge}  •  <b>{listing.deal_score}/100</b>",
        f'<b><a href="{listing.url}">{escape(listing.title)}</a></b>',
        "",
        f"🔗 {listing.url}",
        "",
    ]

    price_line = f"💶 <b>{_money(listing.price, listing.currency)}</b>"
    if listing.shipping_cost:
        price_line += f"  (+ {_money(listing.shipping_cost, listing.currency)} Versand)"
    lines.append(price_line)

    if listing.estimated_market_price:
        lines.append(f"📈 Marktpreis ~ {_money(listing.estimated_market_price)}")
    if listing.discount_percent and listing.discount_percent > 0:
        saving = None
        if listing.estimated_market_price and listing.price is not None:
            saving = listing.estimated_market_price - listing.price
        save_txt = f" (−{_money(saving)})" if saving and saving > 0 else ""
        lines.append(f"💰 {listing.discount_percent:.0f}% unter Markt{save_txt}")

    meta: list[str] = [f"🏷 {listing.site.value}"]
    if listing.location:
        meta.append(f"📍 {escape(listing.location)}")
    if listing.is_auction:
        meta.append("🔨 Auktion")
    lines.append("  •  ".join(meta))

    if listing.description:
        desc = escape(listing.description[:180])
        lines += ["", f"<i>{desc}{'…' if len(listing.description) > 180 else ''}</i>"]

    return "\n".join(lines)


def format_resale_line(listing: Listing) -> str | None:
    """If the item looks profitable to flip, return an ROI summary line."""
    market = listing.estimated_market_price
    if market is None or listing.price is None or listing.price <= 0:
        return None
    profit = market - listing.price
    if profit <= 0:
        return None
    roi = profit / listing.price * 100
    return (
        f"♻️ <b>Wiederverkauf:</b> kaufen {_money(listing.price)} → "
        f"Markt {_money(market)} = Gewinn {_money(profit)} (ROI {roi:.0f}%)"
    )
