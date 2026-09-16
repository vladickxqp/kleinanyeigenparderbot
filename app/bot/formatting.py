"""Render listings as pretty Telegram HTML deal cards.

Every label goes through the translation layer: the deal card is by far the
most-seen text in the product, so a user who picked English at /start must not
get German here.
"""

from __future__ import annotations

from html import escape

from app.bot.texts import t
from app.database.models import Listing
from app.database.models.enums import DealVerdict

_VERDICT_KEY: dict[DealVerdict, str] = {
    DealVerdict.STEAL: "card.verdict.steal",
    DealVerdict.GREAT: "card.verdict.great",
    DealVerdict.GOOD: "card.verdict.good",
    DealVerdict.FAIR: "card.verdict.fair",
    DealVerdict.OVERPRICED: "card.verdict.overpriced",
    DealVerdict.UNKNOWN: "card.verdict.unknown",
}


def _money(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "—"
    symbol = "€" if currency == "EUR" else currency
    return f"{value:,.0f} {symbol}".replace(",", ".")


def verdict_badge(verdict: DealVerdict, lang: str = "de") -> str:
    key = _VERDICT_KEY.get(verdict)
    return t(key, lang) if key else ""


def format_deal_card(listing: Listing, lang: str = "de") -> str:
    """Build the HTML caption for a deal notification card."""
    badge = verdict_badge(listing.deal_verdict, lang)
    # Title doubles as a clickable link so the offer is always one tap away,
    # in addition to the "open" button below the card.
    # The URL comes from scraped markup, so it is escaped like any other
    # untrusted text before it goes into an HTML attribute.
    safe_url = escape(listing.url, quote=True)
    lines: list[str] = [
        f"{badge}  •  <b>{listing.deal_score}/100</b>",
        f'<b><a href="{safe_url}">{escape(listing.title)}</a></b>',
        "",
        f"🔗 {safe_url}",
        "",
    ]

    price_line = f"💶 <b>{_money(listing.price, listing.currency)}</b>"
    if getattr(listing, "is_negotiable", False):
        price_line += f"  <i>{t('card.negotiable', lang)}</i>"
    if listing.shipping_cost:
        amount = _money(listing.shipping_cost, listing.currency)
        price_line += f"  ({t('card.shipping_cost', lang, amount=amount)})"
    elif listing.shipping_cost == 0:
        # Parsers encode "seller offers shipping" as a zero cost.
        price_line += f"  ({t('card.shipping_possible', lang)})"
    lines.append(price_line)

    # Price-drop re-notification: show where the price came from.
    if (
        listing.original_price
        and listing.price is not None
        and listing.original_price > listing.price
    ):
        saved = listing.original_price - listing.price
        lines.append(
            t(
                "card.price_drop",
                lang,
                before=_money(listing.original_price, listing.currency),
                now=_money(listing.price, listing.currency),
                saved=_money(saved),
            )
        )

    if listing.estimated_market_price:
        lines.append(
            t(
                "card.market_price",
                lang,
                amount=_money(listing.estimated_market_price),
            )
        )
    if listing.discount_percent and listing.discount_percent > 0:
        saving = None
        if listing.estimated_market_price and listing.price is not None:
            saving = listing.estimated_market_price - listing.price
        save_txt = f" (−{_money(saving)})" if saving and saving > 0 else ""
        lines.append(
            t(
                "card.below_market",
                lang,
                percent=f"{listing.discount_percent:.0f}",
                saving=save_txt,
            )
        )

    meta: list[str] = [f"🏷 {listing.site.value}"]
    if listing.location:
        meta.append(f"📍 {escape(listing.location)}")
    if listing.is_auction:
        meta.append(t("card.auction", lang))
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


def format_resale_line(listing: Listing, lang: str = "de") -> str | None:
    """If the item is profitable to flip AFTER fees, return a summary line."""
    market = listing.estimated_market_price
    if market is None or listing.price is None or listing.price <= 0:
        return None
    net = net_flip_profit(listing.price, market)
    if net <= 0:
        return None
    roi = net / listing.price * 100
    return t(
        "card.flip",
        lang,
        buy=_money(listing.price),
        market=_money(market),
        net=_money(net),
        roi=f"{roi:.0f}",
    )
