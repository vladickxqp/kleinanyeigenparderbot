"""Keyboard builders. Callback data uses simple ``action:payload`` strings."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import t
from app.config.settings import settings
from app.database.models import Listing, SearchRule


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.rules", lang), callback_data="menu:rules")
    kb.button(text=t("btn.new_rule", lang), callback_data="rule:new")
    kb.button(text=t("btn.favorites", lang), callback_data="menu:favorites")
    kb.button(text=t("btn.stats", lang), callback_data="menu:stats")
    kb.button(text=t("btn.settings", lang), callback_data="menu:settings")
    kb.button(text=t("btn.help", lang), callback_data="menu:help")
    kb.button(text="💎 Premium", callback_data="menu:premium")
    kb.button(text="💬 Support", callback_data="menu:support")
    kb.button(text="📦 Meine Flips", callback_data="menu:flips")
    kb.adjust(2, 2, 2, 2, 1)
    if settings.webapp_url:
        # Only shown once a public HTTPS URL is configured (WEBAPP_URL).
        kb.row(
            InlineKeyboardButton(
                text="🌐 App öffnen", web_app=WebAppInfo(url=settings.webapp_url)
            )
        )
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
    kb.button(text="▶️ Jetzt suchen", callback_data=f"rule:run:{rule.id}")
    kb.button(text=t("btn.edit", lang), callback_data=f"rule:edit:{rule.id}")
    kb.button(text=t("btn.toggle", lang), callback_data=f"rule:toggle:{rule.id}")
    kb.button(text=t("btn.delete", lang), callback_data=f"rule:delete:{rule.id}")
    kb.button(text=t("btn.back", lang), callback_data="menu:rules")
    kb.adjust(1, 1, 2, 1)
    return kb.as_markup()


def rule_edit_keyboard(rule: SearchRule, lang: str) -> InlineKeyboardMarkup:
    """One button per editable field of a rule."""
    rid = rule.id
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Name", callback_data=f"edit:name:{rid}")
    kb.button(text="🔎 Suchwörter", callback_data=f"edit:keywords:{rid}")
    kb.button(text="📂 Kategorie", callback_data=f"edit:category:{rid}")
    kb.button(text="💶 Preis", callback_data=f"edit:price:{rid}")
    kb.button(text="🚫 Ausschluss", callback_data=f"edit:exclude:{rid}")
    kb.button(text="📍 Ort", callback_data=f"edit:location:{rid}")
    kb.button(text="⏱ Intervall", callback_data=f"edit:interval:{rid}")
    kb.button(text="🎯 Min-Score", callback_data=f"edit:minscore:{rid}")
    kb.adjust(2, 2, 2, 2)
    kb.row(
        InlineKeyboardButton(
            text=t("btn.back", lang), callback_data=f"rule:open:{rid}"
        )
    )
    return kb.as_markup()


def listing_actions_keyboard(listing: Listing, lang: str) -> InlineKeyboardMarkup:
    """Buttons attached to a deal card: open, favorite, negotiate, ignore, track."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔗 Öffnen / Open", url=listing.url))
    kb.button(text="⭐", callback_data=f"listing:fav:{listing.id}")
    kb.button(text="🤝", callback_data=f"listing:nego:{listing.id}")
    kb.button(text="🙈", callback_data=f"listing:ignore:{listing.id}")
    kb.button(text="👁 Preis", callback_data=f"listing:track:{listing.id}")
    kb.row(
        InlineKeyboardButton(
            text="🛒 Gekauft — Flip tracken", callback_data=f"listing:buy:{listing.id}"
        )
    )
    kb.adjust(1, 4, 1)
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
# Minimum is 1 minute: sub-minute polling gets the user's IP blocked by the
# marketplaces (silent zero-result pages) without finding deals any faster.
INTERVAL_CHOICES: list[tuple[int, str]] = [
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
    kb.adjust(3, 2)
    kb.row(
        InlineKeyboardButton(text=t("btn.cancel", lang), callback_data="wizard:cancel")
    )
    return kb.as_markup()


# Category choices: (slug stored on the rule, label shown to the user).
# Parsers map these slugs to their site-specific category ids.
CATEGORY_CHOICES: list[tuple[str, str]] = [
    ("handys", "📱 Handys"),
    ("notebooks", "💻 Notebooks"),
    ("pcs", "🖥 PCs"),
    ("pc-zubehoer", "🎮 GPU / PC-Teile"),
    ("konsolen", "🕹 Konsolen"),
    ("elektronik", "🔌 Elektronik"),
    ("autos", "🚗 Autos"),
    ("fahrraeder", "🚲 Fahrräder"),
]


def category_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Pick a category for the search (or all)."""
    kb = InlineKeyboardBuilder()
    for slug, label in CATEGORY_CHOICES:
        kb.button(text=label, callback_data=f"wizcat:{slug}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(
            text=t("btn.all_categories", lang), callback_data="wizcat:none"
        ),
        InlineKeyboardButton(text=t("btn.cancel", lang), callback_data="wizard:cancel"),
    )
    return kb.as_markup()


#: Radius options (km) for the Kleinanzeigen Umkreissuche.
RADIUS_CHOICES: list[int] = [5, 10, 25, 50, 100, 200]


def radius_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Pick the search radius around the chosen location."""
    kb = InlineKeyboardBuilder()
    for km in RADIUS_CHOICES:
        kb.button(text=f"📏 {km} km", callback_data=f"wizrad:{km}")
    kb.adjust(3, 3)
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
