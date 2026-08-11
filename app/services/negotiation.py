"""Negotiation assistant: suggest an opening offer and a ready-to-send message.

Deterministic and free of external dependencies — no AI key required. The
suggested offer is a configurable percentage below asking, rounded to a
"human" number (nobody offers 437 €; 430 € reads natural).
"""

from __future__ import annotations

from app.config.settings import settings


def suggest_offer(price: float, discount_percent: float | None = None) -> int:
    """A realistic opening offer below the asking price, nicely rounded."""
    discount = (
        discount_percent
        if discount_percent is not None
        else settings.nego_discount_percent
    )
    raw = price * (1 - discount / 100)

    if raw < 20:
        step = 1
    elif raw < 200:
        step = 5
    elif raw < 1000:
        step = 10
    elif raw < 10_000:
        step = 50
    else:
        step = 100
    offer = int(round(raw / step) * step)
    # Never suggest the asking price itself (or more) for positive prices.
    if offer >= price and price >= 1:
        offer = max(1, int(price) - step)
    return max(1, offer)


def build_message(title: str, price: float, offer: int) -> str:
    """A polite, effective German negotiation message (plain text, copyable)."""
    return (
        f"Guten Tag! Ich interessiere mich für Ihre Anzeige "
        f"„{title[:60]}“. "
        f"Wäre der Preis noch etwas verhandelbar? "
        f"Ich könnte Ihnen {offer} € anbieten und das Ganze zeitnah "
        f"abholen bzw. sofort bezahlen. "
        f"Viele Grüße!"
    )
