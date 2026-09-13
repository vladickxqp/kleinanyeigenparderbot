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

    # Price-drop re-notification: show where the price came from.
    if (
        listing.original_price
        and listing.price is not None
        and listing.original_price > listing.price
    ):
        saved = listing.original_price - listing.price
        lines.append(
            f"📉 <b>PREISSTURZ:</b> {_money(listing.original_price, listing.currency)} "
            f"→ {_money(listing.price, listing.currency)} (−{_money(saved)})"
        )

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


def net_flip_profit(price: float, market: float) -> float:
    """Reseller math: sale price − fees − shipping − purchase price.

    Delegates to the flip service so the card estimate and the realised
    profit in /flips are computed by exactly the same formula.
    """
    from app.services.flips import estimated_net_profit

    return estimated_net_profit(price, market)


def format_resale_line(listing: Listing) -> str | None:
    """If the item is profitable to flip AFTER fees, return a summary line."""
    market = listing.estimated_market_price
    if market is None or listing.price is None or listing.price <= 0:
        return None
    net = net_flip_profit(listing.price, market)
    if net <= 0:
        return None
    roi = net / listing.price * 100
    return (
        f"♻️ <b>Flip:</b> Kauf {_money(listing.price)} → Markt {_money(market)} "
        f"= <b>{_money(net)} netto</b> nach Gebühren (ROI {roi:.0f}%)"
    )
