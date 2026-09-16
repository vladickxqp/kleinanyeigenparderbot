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
from app.database.models.enums import Condition


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


def rule_edit_keyboard(
    rule: SearchRule, lang: str, *, has_rule_power: bool = True
) -> InlineKeyboardMarkup:
    """One button per editable field of a rule.

    ``has_rule_power`` only decides what the menu SHOWS. The handler checks the
    entitlement again on every tap, so a caller that does not know the user's
    level may leave the default instead of locking a paying user out.
    """
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
    if has_rule_power:
        # The label carries the current value: these three are invisible on the
        # rule card, so the menu is the only place a user can check them.
        kb.button(
            text=f"🏷 Zustand: {condition_short(rule.condition)}",
            callback_data=f"edit:condition:{rid}",
        )
        kb.button(
            text=f"📦 Versand: {shipping_short(rule.shipping_available)}",
            callback_data=f"edit:shipping:{rid}",
        )
        kb.button(
            text=f"🔨 Auktionen: {auction_short(rule.exclude_auctions)}",
            callback_data=f"edit:auctions:{rid}",
        )
        kb.adjust(2, 2, 2, 2, 2, 1)
    else:
        kb.adjust(2, 2, 2, 2)
        kb.row(
            InlineKeyboardButton(
                text="🔒 Zustand · Versand · Auktionen",
                callback_data=f"edit:locked:{rid}",
            )
        )
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


# --- Rule power filters (Zustand / Versand / Auktionen) -----------------------
# Only ANY/NEW/USED/DEFECTIVE are offered: LIKE_NEW and REFURBISHED have no
# dependable marker in German ad texts, and eBay folds them into "gebraucht"
# anyway — a filter nobody can satisfy is worse than no filter.
CONDITION_CHOICES: list[tuple[str, str]] = [
    ("any", "🔀 Egal"),
    ("new", "✨ Neu / OVP"),
    ("used", "📦 Gebraucht"),
    ("defective", "🔧 Defekt / Bastler"),
]

#: Short forms for the edit-menu button. Legacy values are listed too, so a
#: rule written by an older version still renders a readable label.
_CONDITION_SHORT: dict[str, str] = {
    "any": "egal",
    "new": "neu",
    "used": "gebraucht",
    "defective": "defekt",
    "like_new": "wie neu",
    "refurbished": "refurbished",
}

#: Shipping choice slug -> value stored on the rule (None = does not matter).
SHIPPING_VALUES: dict[str, bool | None] = {"any": None, "yes": True, "no": False}
SHIPPING_CHOICES: list[tuple[str, str]] = [
    ("any", "🔀 Egal"),
    ("yes", "📦 Nur mit Versand"),
    ("no", "🚗 Nur Abholung"),
]

#: Auction choice slug -> value stored on SearchRule.exclude_auctions.
AUCTION_VALUES: dict[str, bool] = {"keep": False, "hide": True}
AUCTION_CHOICES: list[tuple[str, str]] = [
    ("keep", "🔨 Auktionen zeigen"),
    ("hide", "🚫 Auktionen ausblenden"),
]


def condition_short(value: Condition | None) -> str:
    """Label for the current condition (None until the INSERT applies the default)."""
    if value is None:
        return _CONDITION_SHORT["any"]
    return _CONDITION_SHORT.get(value.value, value.value)


def shipping_short(value: bool | None) -> str:
    """Label for the current shipping filter — None genuinely means "egal"."""
    if value is None:
        return "egal"
    return "mit Versand" if value else "nur Abholung"


def auction_short(exclude_auctions: bool | None) -> str:
    return "aus" if exclude_auctions else "an"


def condition_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Pick which item condition a rule should keep."""
    kb = InlineKeyboardBuilder()
    for slug, label in CONDITION_CHOICES:
        kb.button(text=label, callback_data=f"wizcond:{slug}")
    kb.adjust(2, 2)
    kb.row(
        InlineKeyboardButton(text=t("btn.cancel", lang), callback_data="wizard:cancel")
    )
    return kb.as_markup()


def shipping_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Pick whether the rule wants shippable ads, pickup-only ads or both."""
    kb = InlineKeyboardBuilder()
    for slug, label in SHIPPING_CHOICES:
        kb.button(text=label, callback_data=f"wizship:{slug}")
    kb.adjust(1)
    kb.row(
        InlineKeyboardButton(text=t("btn.cancel", lang), callback_data="wizard:cancel")
    )
    return kb.as_markup()


def auctions_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Show or hide auction listings for this rule."""
    kb = InlineKeyboardBuilder()
    for slug, label in AUCTION_CHOICES:
        kb.button(text=label, callback_data=f"wizauc:{slug}")
    kb.adjust(1)
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
