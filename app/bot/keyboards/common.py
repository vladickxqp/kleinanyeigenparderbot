"""Keyboard builders. Callback data uses simple ``action:payload`` strings."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import t
from app.database.models import Listing, SearchRule


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.rules", lang), callback_data="menu:rules")
    kb.button(text=t("btn.new_rule", lang), callback_data="rule:new")
    kb.button(text=t("btn.favorites", lang), callback_data="menu:favorites")
    kb.button(text=t("btn.stats", lang), callback_data="menu:stats")
    kb.button(text=t("btn.settings", lang), callback_data="menu:settings")
    kb.button(text=t("btn.help", lang), callback_data="menu:help")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.cancel", lang), callback_data="wizard:cancel")
    return kb.as_markup()


def skip_cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.skip", lang), callback_data="wizard:skip")
    kb.button(text=t("btn.cancel", lang), callback_data="wizard:cancel")
    kb.adjust(2)
    return kb.as_markup()


def rules_list_keyboard(rules: Sequence[SearchRule], lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for rule in rules:
        state = "🟢" if rule.is_active else "⚪️"
        kb.button(text=f"{state} {rule.name}", callback_data=f"rule:open:{rule.id}")
    kb.button(text=t("btn.new_rule", lang), callback_data="rule:new")
    kb.button(text=t("btn.back", lang), callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def rule_actions_keyboard(rule: SearchRule, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.toggle", lang), callback_data=f"rule:toggle:{rule.id}")
    kb.button(text=t("btn.delete", lang), callback_data=f"rule:delete:{rule.id}")
    kb.button(text=t("btn.back", lang), callback_data="menu:rules")
    kb.adjust(2, 1)
    return kb.as_markup()


def listing_actions_keyboard(listing: Listing, lang: str) -> InlineKeyboardMarkup:
    """Buttons attached to a deal card: open, favorite, ignore, track."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔗 Öffnen / Open", url=listing.url))
    kb.button(text="⭐", callback_data=f"listing:fav:{listing.id}")
    kb.button(text="🙈", callback_data=f"listing:ignore:{listing.id}")
    kb.button(text="👁 Preis", callback_data=f"listing:track:{listing.id}")
    kb.adjust(1, 3)
    return kb.as_markup()


def sites_select_keyboard(
    available: list[str], selected: list[str], lang: str
) -> InlineKeyboardMarkup:
    """Multi-select keyboard for choosing which marketplaces to search."""
    kb = InlineKeyboardBuilder()
    for site in available:
        mark = "☑️" if site in selected else "⬜️"
        kb.button(text=f"{mark} {site.title()}", callback_data=f"wizsite:toggle:{site}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(
            text=t("btn.all_platforms", lang), callback_data="wizsite:all"
        ),
        InlineKeyboardButton(text=t("btn.done", lang), callback_data="wizsite:done"),
    )
    return kb.as_markup()


# Human-friendly interval choices (seconds, label). Used by the rule wizard.
INTERVAL_CHOICES: list[tuple[int, str]] = [
    (10, "10 s"),
    (30, "30 s"),
    (60, "1 min"),
    (300, "5 min"),
    (600, "10 min"),
    (1800, "30 min"),
    (3600, "1 h"),
]


def interval_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Pick how often a rule should be checked."""
    kb = InlineKeyboardBuilder()
    for seconds, label in INTERVAL_CHOICES:
        kb.button(text=f"⏱ {label}", callback_data=f"wizint:{seconds}")
    kb.adjust(4, 3)
    kb.row(
        InlineKeyboardButton(text=t("btn.cancel", lang), callback_data="wizard:cancel")
    )
    return kb.as_markup()


def language_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇩🇪 Deutsch", callback_data="lang:de")
    kb.button(text="🇬🇧 English", callback_data="lang:en")
    kb.button(text="🇷🇺 Русский", callback_data="lang:ru")
    kb.button(text="🇺🇦 Українська", callback_data="lang:uk")
    kb.adjust(2, 2)
    return kb.as_markup()
