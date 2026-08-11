"""Tiny shared formatting helpers (aiogram-free, unit-testable)."""

from __future__ import annotations


def money(value: float | None, currency: str = "EUR") -> str:
    """Format an amount as German-style currency: 1.234 €."""
    if value is None:
        return "—"
    symbol = "€" if currency == "EUR" else currency
    return f"{value:,.0f} {symbol}".replace(",", ".")
