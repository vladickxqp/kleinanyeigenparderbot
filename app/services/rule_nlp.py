"""Turn one German sentence into a ready-to-save search rule.

The creation wizard asks eight questions before the user sees a single result,
and that is where most people quit. This module is the short path: the user
writes *"Tesla Model 3 unter 25.000 Euro, höchstens 100.000 km, 100 km um
Worms"* and gets a finished rule proposal to confirm or adjust.

Two layers, strictly in this order:

1. A **deterministic German parser** (:func:`parse_rule_text`). It works with
   AI switched off, it is the only layer the tests drive, and every value it
   produces is already validated.
2. An **optional AI refinement** (:func:`refine_with_ai`) that may only *fill
   what the rules could not*. It never overwrites a value the deterministic
   layer found, it may only return the known field set, every single value is
   re-validated through the same helpers as layer 1, and any failure, timeout
   or nonsense answer falls back to the deterministic draft. No model-produced
   value ever reaches the database unchecked.

The whole feature is gated by ``settings.nl_rules_enabled`` (see
:func:`is_enabled`); the AI layer additionally by :func:`app.services.ai.is_available`.

Kept aiogram-free on purpose, exactly like :mod:`app.services.parsing`, so it
is unit-testable without the Telegram stack.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.config.settings import settings
from app.database.models.enums import Condition
from app.services import ai
from app.services.parsing import parse_price_range

# --- Limits (all values are clamped to these before they leave the module) ----
#: Longest free text we look at. Bounds the regex work on hostile input.
MAX_INPUT_CHARS = 500
#: Ein Baujahr ausserhalb dieser Spanne meint etwas anderes.
MIN_YEAR = 1950
MAX_YEAR = 2100
MAX_NAME_CHARS = 128
MAX_KEYWORDS_CHARS = 256
#: The wizard cuts a location to 64 chars (the column allows 128).
MAX_LOCATION_CHARS = 64
MAX_EXCLUDE_WORDS = 10
MAX_EXCLUDE_CHARS = 32
#: Nothing sane on these marketplaces costs more; a bigger number is a typo or
#: a model number that slipped through, and must not become a price filter.
MAX_PRICE_EUR = 10_000_000.0
MAX_MILEAGE_KM = 2_000_000
#: Radii the search wizard offers (mirrors ``keyboards.RADIUS_CHOICES``; kept
#: local so this module stays importable without the bot stack). A free-text
#: radius is snapped to the next larger of these, so a rule created from a
#: sentence looks exactly like one clicked together by hand and never searches
#: a SMALLER area than the user asked for.
ALLOWED_RADII_KM: tuple[int, ...] = (5, 10, 25, 50, 100, 200)

#: How long the optional AI pass may take before we keep the regex result.
AI_TIMEOUT_SECONDS = 12.0

#: Where a draft's values came from — shown to the user, useful in logs.
SOURCE_RULES = "rules"
SOURCE_AI = "ai"


@dataclass(slots=True)
class RuleDraft:
    """The subset of :class:`~app.database.models.SearchRule` we can infer.

    Only fields a sentence can plausibly carry. Everything else (category,
    sites, interval, deal score) keeps the same defaults the wizard uses.
    """

    keywords: str = ""
    name: str = ""
    min_price: float | None = None
    max_price: float | None = None
    exclude_keywords: list[str] = field(default_factory=list)
    location: str | None = None
    zip_code: str | None = None
    max_distance_km: int | None = None
    condition: Condition = Condition.ANY
    max_mileage_km: int | None = None
    #: Erstzulassung ab. Wie die Kilometer ein Auto-Feld; beide muessen
    #: vor der Preissuche gelesen werden, sonst wird "ab 2018" ein
    #: Mindestpreis von 2018 Euro.
    min_year: int | None = None
    source: str = SOURCE_RULES

    @property
    def is_usable(self) -> bool:
        """A draft without search words cannot become a rule."""
        return bool(self.keywords.strip())

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-able form (FSM storage between message and button tap)."""
        return {
            "keywords": self.keywords,
            "name": self.name,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "exclude_keywords": list(self.exclude_keywords),
            "location": self.location,
            "zip_code": self.zip_code,
            "max_distance_km": self.max_distance_km,
            "condition": self.condition.value,
            "max_mileage_km": self.max_mileage_km,
            "min_year": self.min_year,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RuleDraft":
        """Rebuild a draft from storage — re-validating every field.

        The round-trip goes through an external store, so this is treated with
        the same suspicion as a model answer.
        """
        if not isinstance(data, dict):
            return cls()
        draft = cls(
            keywords=_clean_text(data.get("keywords"), MAX_KEYWORDS_CHARS) or "",
            name=_clean_text(data.get("name"), MAX_NAME_CHARS) or "",
            min_price=_coerce_price(data.get("min_price")),
            max_price=_coerce_price(data.get("max_price")),
            exclude_keywords=_coerce_excludes(data.get("exclude_keywords")),
            location=_clean_text(data.get("location"), MAX_LOCATION_CHARS),
            zip_code=_coerce_zip(data.get("zip_code")),
            max_distance_km=_coerce_distance(data.get("max_distance_km")),
            condition=_coerce_condition(data.get("condition")),
            max_mileage_km=_coerce_mileage(data.get("max_mileage_km")),
            min_year=_coerce_year(data.get("min_year")),
            source=str(data.get("source") or SOURCE_RULES)[:16],
        )
        return _finalize(draft)


def is_enabled() -> bool:
    """Master switch for the whole free-text path (``NL_RULES_ENABLED``)."""
    return bool(settings.nl_rules_enabled)


# --- Shared validation ------------------------------------------------------
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean_text(value: Any, limit: int) -> str | None:
    """Collapse whitespace, drop control characters, cut to ``limit``."""
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        value = "" if value is None or isinstance(value, bool) else str(value)
    if not isinstance(value, str):
        return None
    text = _CONTROL_CHARS.sub(" ", value)
    text = " ".join(text.split()).strip()
    if not text:
        return None
    return text[:limit]


def _coerce_price(value: Any) -> float | None:
    """A price is a positive number below :data:`MAX_PRICE_EUR` — or nothing.

    Strings go through the wizard's own :func:`parse_price_range`, so "18.000",
    "1.200,50" and "20000 €" mean the same here as in every other input field.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        parsed = parse_price_range(value)
        if parsed is None:
            return None
        number = parsed[1] if parsed[1] is not None else parsed[0]  # type: ignore[assignment]
        if number is None:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return None
    if number <= 0 or number > MAX_PRICE_EUR:
        return None
    return round(float(number), 2)


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return int(number)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits and len(digits) <= 12 else None
    return None


def _coerce_distance(value: Any) -> int | None:
    """Snap a radius onto the set the wizard offers (next larger choice)."""
    km = _coerce_int(value)
    if km is None or km <= 0:
        return None
    for choice in ALLOWED_RADII_KM:
        if km <= choice:
            return choice
    return ALLOWED_RADII_KM[-1]


def _coerce_mileage(value: Any) -> int | None:
    km = _coerce_int(value)
    if km is None or km <= 0 or km > MAX_MILEAGE_KM:
        return None
    return km


def _coerce_year(value: Any) -> int | None:
    """Ein Baujahr ist vierstellig und liegt in der Gegenwart."""
    year = _coerce_int(value)
    if year is None or year < MIN_YEAR or year > MAX_YEAR:
        return None
    return year


def _coerce_zip(value: Any) -> str | None:
    """German postcodes only: exactly five digits, nothing else."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if re.fullmatch(r"\d{5}", text) else None


_CONDITION_SYNONYMS: dict[str, Condition] = {
    "any": Condition.ANY,
    "egal": Condition.ANY,
    "new": Condition.NEW,
    "neu": Condition.NEW,
    "like_new": Condition.LIKE_NEW,
    "wie neu": Condition.LIKE_NEW,
    "neuwertig": Condition.LIKE_NEW,
    "used": Condition.USED,
    "gebraucht": Condition.USED,
    "defective": Condition.DEFECTIVE,
    "defekt": Condition.DEFECTIVE,
    "bastler": Condition.DEFECTIVE,
    "refurbished": Condition.REFURBISHED,
    "generalüberholt": Condition.REFURBISHED,
}


def _coerce_condition(value: Any) -> Condition:
    if isinstance(value, Condition):
        return value
    if not isinstance(value, str):
        return Condition.ANY
    return _CONDITION_SYNONYMS.get(value.strip().lower(), Condition.ANY)


def _coerce_excludes(value: Any) -> list[str]:
    """A short, deduplicated list of short words — never a model's essay."""
    if isinstance(value, str):
        value = [part for part in re.split(r"[,;]", value)]
    if not isinstance(value, (list, tuple)):
        return []
    words: list[str] = []
    seen: set[str] = set()
    for item in value:
        word = _clean_text(item, MAX_EXCLUDE_CHARS)
        if not word:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= MAX_EXCLUDE_WORDS:
            break
    return words


def _format_amount(value: float) -> str:
    """German thousands separators: 25000.0 -> "25.000"."""
    return f"{value:,.0f}".replace(",", ".")


def _build_name(draft: RuleDraft) -> str:
    base = draft.keywords.strip() or "Suche"
    if draft.min_price is not None and draft.max_price is not None:
        suffix = f" {_format_amount(draft.min_price)}–{_format_amount(draft.max_price)} €"
    elif draft.max_price is not None:
        suffix = f" bis {_format_amount(draft.max_price)} €"
    elif draft.min_price is not None:
        suffix = f" ab {_format_amount(draft.min_price)} €"
    else:
        suffix = ""
    return (base + suffix)[:MAX_NAME_CHARS].strip()


def _finalize(draft: RuleDraft) -> RuleDraft:
    """Last pass over a draft: consistent bounds, lengths, derived name."""
    if (
        draft.min_price is not None
        and draft.max_price is not None
        and draft.min_price > draft.max_price
    ):
        draft.min_price, draft.max_price = draft.max_price, draft.min_price
    draft.keywords = (draft.keywords or "").strip()[:MAX_KEYWORDS_CHARS]
    # An exclude word that IS the search term would leave a rule that can never
    # match anything.
    lowered = draft.keywords.lower()
    draft.exclude_keywords = [
        word for word in draft.exclude_keywords if word.lower() != lowered
    ]
    if draft.zip_code and not draft.location:
        draft.location = draft.zip_code
    if draft.max_distance_km is not None and not (draft.location or draft.zip_code):
        # A radius without a centre means nothing to any parser.
        draft.max_distance_km = None
    if draft.location:
        draft.location = draft.location[:MAX_LOCATION_CHARS]
    draft.name = _clean_text(draft.name, MAX_NAME_CHARS) or _build_name(draft)
    return draft


# --- Deterministic German parser --------------------------------------------
#: Words that must never be swallowed as part of a place or an exclude term.
_STOP_WORDS: tuple[str, ...] = (
    "und", "oder", "aber", "sowie", "mit", "ohne", "kein", "keine", "keinen",
    "keinem", "nicht", "bis", "ab", "unter", "über", "ueber", "max", "maximal",
    "höchstens", "hoechstens", "mindestens", "min", "zwischen", "für", "fuer",
    "euro", "eur", "km", "tkm", "kilometer", "umkreis", "nähe", "naehe", "raum",
    "region", "plz", "nur", "noch", "auch", "der", "die", "das", "den", "dem",
    "ein", "eine", "einen", "einem", "von", "vom", "zu", "zum", "zur", "im",
    "in", "am", "an", "auf", "bei", "als", "etwa", "ca", "circa", "budget",
    "preis", "kosten", "mehr", "weniger", "teurer", "billiger", "günstiger",
    "guenstiger", "älter", "neuer", "weiter",
)
_STOP_ALT = "|".join(_STOP_WORDS)

#: One token of a German word (the text is lower-cased before matching).
_TOKEN = r"[a-zäöüß][a-zäöüß0-9'\-\.]*"
#: A place: a postcode, or one/two words that are not stop words.
_PLACE = (
    rf"(?P<place>\d{{5}}|{_TOKEN}(?:\s+(?!(?:{_STOP_ALT})\b){_TOKEN})?)"
)
#: A number, anchored so the regex cannot backtrack into "100.00" of "100.000".
_NUM = r"(?P<num>\d[\d.,]*)(?![\d.,])"
_CUR = r"(?:\s*(?:€|euro|eur))?"
#: Guard: what follows must not be a unit — "höchstens 100.000 km" is mileage,
#: never a price.
_NOT_UNIT = r"(?!\s*(?:km|tkm|kilometer|ps|kw|gb|tb|zoll|stück|stk))"

# 1) Negations: "keine Bastler", "ohne Kratzer", "kein Defekt".
_NEGATION_RE = re.compile(
    rf"\b(?:keine|keinen|keinem|kein|ohne|nicht)\s+"
    rf"(?P<w1>{_TOKEN})(?:\s+(?P<w2>{_TOKEN}))?"
)

# 2) Distance + place: "100 km um Worms", "Umkreis 50 km", "50 km Umkreis".
_DISTANCE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"(?P<km>\d{{1,4}})\s*km\s+(?:im\s+)?"
        rf"(?:umkreis\s+(?:um|von)\s+|rund\s+um\s+|um\s+|von\s+)"
        rf"(?:die\s+|der\s+|das\s+)?{_PLACE}"
    ),
    re.compile(rf"(?P<km>\d{{1,4}})\s*km\s+umkreis(?:\s+(?:um|von)\s+{_PLACE})?"),
    re.compile(
        rf"umkreis\s*(?:von\s+|um\s+|:\s*)?(?P<km>\d{{1,4}})\s*km"
        rf"(?:\s+(?:um|von)\s+{_PLACE})?"
    ),
)

# 3) Place without a radius. The second group needs the original word to be
#    capitalised: "in Köln" is a place, "in schwarz" is a colour.
_LOCATION_RES: tuple[tuple[re.Pattern[str], bool], ...] = (
    (
        re.compile(
            rf"\b(?:in\s+der\s+n(?:ä|ae)he\s+von|n(?:ä|ae)he|umgebung\s+von|"
            rf"raum|region|rund\s+um|um)\s+{_PLACE}"
        ),
        False,
    ),
    (re.compile(rf"\b(?:in|aus|bei)\s+{_PLACE}"), True),
    (re.compile(rf"\bplz\s*:?\s*(?P<place>\d{{5}})"), False),
)

# 4) Mileage: "höchstens 100.000 km", "120tkm", "120k km".
_MILEAGE_RE = re.compile(
    rf"(?:(?:bis\s+zu|bis|max\.?|maximal|h(?:ö|oe)chstens|unter|weniger\s+als|"
    rf"nicht\s+mehr\s+als)\s+)?{_NUM}\s*(?P<unit>tkm|k\s*km|km)\b"
)

# 4b) Baujahr: "ab Baujahr 2018", "EZ ab 2018", "Baujahr 2018".
#     Die Jahreszahl braucht ein Wort davor - eine nackte 2018 im Satz
#     ist oefter ein Preis oder eine Modellnummer als ein Baujahr.
_YEAR_RE = re.compile(
    r"(?:baujahr|bj\.?|erstzulassung|ez|zulassung)\s*"
    r"(?:ab|seit|von|ab\s+dem)?\s*(?P<year>(?:19|20)\d{2})\b"
    r"|(?:ab|seit|neuer\s+als|juenger\s+als|j(?:ü|ue)nger\s+als)\s+"
    r"(?:baujahr|bj\.?|erstzulassung|ez)?\s*(?P<year2>(?:19|20)\d{2})\b"
    # "ab 2018 €" ist ein Mindestpreis, kein Baujahr. Eine Zahl mit Waehrung
    # dahinter gehoert der Preissuche, die gleich danach laeuft.
    r"(?!\s*(?:€|euro|eur))"
)

# 5) Prices. Ranges first — "bis" inside "zwischen 500 und 900" must not be
#    read as a maximum. A bare "A bis B" is deliberately NOT a range: in
#    "RTX 4090 bis 900 €" the first number is a model, not a lower bound.
_RANGE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"zwischen\s+(?P<a>\d[\d.,]*)(?![\d.,])\s*(?P<ka>k\b)?{_CUR}\s*"
        rf"(?:und|bis|-|–)\s*(?P<b>\d[\d.,]*)(?![\d.,])\s*(?P<kb>k\b)?{_CUR}{_NOT_UNIT}"
    ),
    re.compile(
        rf"von\s+(?P<a>\d[\d.,]*)(?![\d.,])\s*(?P<ka>k\b)?{_CUR}\s*"
        rf"(?:bis|-|–)\s*(?P<b>\d[\d.,]*)(?![\d.,])\s*(?P<kb>k\b)?{_CUR}{_NOT_UNIT}"
    ),
    re.compile(
        rf"(?P<a>\d[\d.,]*)(?![\d.,])\s*(?P<ka>k\b)?\s*(?:€|euro|eur)\s*"
        rf"(?:bis|-|–)\s*(?P<b>\d[\d.,]*)(?![\d.,])\s*(?P<kb>k\b)?{_CUR}{_NOT_UNIT}"
    ),
    re.compile(
        rf"(?P<a>\d[\d.,]*)(?![\d.,])\s*(?P<ka>k\b)?\s*(?:-|–)\s*"
        rf"(?P<b>\d[\d.,]*)(?![\d.,])\s*(?P<kb>k\b)?\s*(?:€|euro|eur)"
    ),
    # "25k bis 30k": a k-suffix is money in this domain, never a model number.
    re.compile(
        rf"(?P<a>\d[\d.,]*)(?![\d.,])\s*(?P<ka>k)\b\s*(?:bis|und|-|–)\s*"
        rf"(?P<b>\d[\d.,]*)(?![\d.,])\s*(?P<kb>k\b)?{_CUR}{_NOT_UNIT}"
    ),
)
_MAX_PRICE_RE = re.compile(
    rf"\b(?:unter|bis\s+zu|bis|max\.?|maximal|h(?:ö|oe)chstens|"
    rf"nicht\s+(?:mehr\s+als|über|ueber|teurer\s+als)|weniger\s+als|"
    rf"billiger\s+als|g(?:ü|ue)nstiger\s+als)\s+{_NUM}\s*(?P<k>k\b)?{_CUR}{_NOT_UNIT}"
)
_MIN_PRICE_RE = re.compile(
    rf"\b(?:ab|mindestens|min\.?|mehr\s+als|teurer\s+als|über|ueber)\s+"
    rf"{_NUM}\s*(?P<k>k\b)?{_CUR}{_NOT_UNIT}"
)
#: Last resort: a plain amount with a currency ("Budget 800 €") or a k-suffix
#: ("25k") = a maximum, the same reading :func:`parse_price_range` uses for a
#: lone number.
#: The word boundary belongs to the WORDS only: "€" is not a word character,
#: so a trailing \b after it can never match and the whole fallback would fire
#: for "800 euro" while quietly ignoring "800 €" — the spelling people use.
_BARE_PRICE_RE = re.compile(rf"{_NUM}\s*(?P<k>k\b)?\s*(?:€|euro\b|eur\b)")
_K_PRICE_RE = re.compile(rf"{_NUM}\s*(?P<k>k)\b{_CUR}{_NOT_UNIT}")

# 6) Condition words, most specific first.
_CONDITION_RES: tuple[tuple[re.Pattern[str], Condition], ...] = (
    (re.compile(r"\b(?:wie\s+neu|neuwertig)\b"), Condition.LIKE_NEW),
    (
        re.compile(r"\b(?:refurbished|generalüberholt|generalueberholt|runderneuert)\b"),
        Condition.REFURBISHED,
    ),
    (
        re.compile(r"\b(?:fabrikneu|neuware|originalverpackt|versiegelt|ovp|neu)\b"),
        Condition.NEW,
    ),
    (re.compile(r"\b(?:gebraucht|second\s*hand|secondhand)\b"), Condition.USED),
    (
        re.compile(r"\b(?:defekt|defekte|defektes|bastler|bastlerfahrzeug|"
                   r"ersatzteiltr(?:ä|ae)ger)\b"),
        Condition.DEFECTIVE,
    ),
)

#: Conversational filler that adds nothing to a search query. Price and radius
#: markers are NOT in here: when they survive as words they are part of the
#: product ("iPhone 15 Pro Max"), not a forgotten filter.
_FILLER_WORDS: frozenset[str] = frozenset(
    {
        "suche", "suchen", "such", "gesucht", "ich", "mir", "mich", "bitte",
        "finde", "find", "nach", "brauche", "will", "möchte", "moechte",
        "hätte", "haette", "gerne", "gern", "ein", "eine", "einen", "einem",
        "eines", "der", "die", "das", "den", "dem", "und", "oder", "aber",
        "mit", "für", "fuer", "von", "vom", "zu", "zum", "zur", "im", "in",
        "am", "an", "auf", "bei", "als", "etwa", "ca", "circa", "nur", "noch",
        "hallo", "hi", "danke", "plz", "budget", "preis", "preislich",
        "kosten", "bis", "ab", "so", "ist", "sind", "wäre", "waere",
        # Filter markers that can survive when a neighbouring pattern claimed
        # the value first ("Umkreis 30 km um 67547"). None of them is ever
        # part of a product name.
        "umkreis", "umgebung", "nähe", "naehe", "raum", "region", "rund",
        "km", "tkm", "kilometer", "euro", "eur", "zwischen", "maximal",
        "höchstens", "hoechstens", "mindestens", "unter", "über", "ueber",
        "ohne", "keine", "kein", "keinen", "nicht", "etwa",
    }
)

#: Words a negation may not turn into an exclude term — "nicht über 800" is a
#: price, "nicht mehr als 100.000 km" is mileage.
_NEGATION_SKIP: frozenset[str] = frozenset(
    {
        "über", "ueber", "unter", "mehr", "weniger", "teurer", "billiger",
        "günstiger", "guenstiger", "als", "mehrere", "weit", "weiter",
        "älter", "aelter", "neuer", "und", "oder", "zu", "so", "bis", "ab",
        "max", "maximal", "min", "mindestens", "höchstens", "hoechstens",
    }
)


class _Mask:
    """Tracks which characters of the input a rule has already claimed."""

    __slots__ = ("_taken",)

    def __init__(self, length: int) -> None:
        self._taken = bytearray(length)

    def free(self, start: int, end: int) -> bool:
        return not any(self._taken[start:end])

    def take(self, start: int, end: int) -> None:
        for index in range(start, end):
            self._taken[index] = 1

    def remaining(self, text: str) -> str:
        """The input with every claimed span blanked out."""
        return "".join(
            " " if self._taken[index] else char for index, char in enumerate(text)
        )


def _amount(token: str, thousands: bool = False) -> float | None:
    """One money token -> euros, via the wizard's own number parsing."""
    parsed = parse_price_range(token)
    if parsed is None:
        return None
    value = parsed[1] if parsed[1] is not None else parsed[0]
    if value is None:
        return None
    if thousands:
        value *= 1000
    return _coerce_price(value)


def parse_rule_text(text: str) -> RuleDraft:
    """Parse a German sentence into a :class:`RuleDraft` — no AI involved.

    This is the layer that must work on its own. It never raises: unparsable
    input simply yields a draft whose ``is_usable`` is False.
    """
    draft = RuleDraft()
    raw = (text or "").strip()[:MAX_INPUT_CHARS]
    if not raw:
        return draft

    low = raw.lower()
    if len(low) != len(raw):
        # A few unicode characters change length when lower-cased; then the
        # index mapping below would be wrong, so we work on the lower-cased
        # text for both matching and output.
        raw = low
    mask = _Mask(len(raw))

    _extract_negations(raw, low, mask, draft)
    _extract_distance(raw, low, mask, draft)
    _extract_mileage(low, mask, draft)
    # Vor den Preisen: sonst liest _extract_prices "ab 2018" als
    # Mindestpreis von 2018 Euro und das Baujahr ist weg.
    _extract_year(low, mask, draft)
    _extract_prices(low, mask, draft)
    _extract_location(raw, low, mask, draft)
    _extract_zip(low, mask, draft)
    _extract_condition(low, mask, draft)
    draft.keywords = _extract_keywords(mask.remaining(raw))
    return _finalize(draft)


def _extract_negations(raw: str, low: str, mask: _Mask, draft: RuleDraft) -> None:
    """"keine Bastler" / "ohne Kratzer" become exclude words, not keywords."""
    words: list[str] = []
    for match in _NEGATION_RE.finditer(low):
        if not mask.free(*match.span()):
            continue
        first = match.group("w1")
        if first in _NEGATION_SKIP or first in _FILLER_WORDS:
            # "nicht über 800" — leave it to the price parser.
            continue
        end = match.end("w1")
        second = match.group("w2")
        if (
            second
            and second not in _STOP_WORDS
            and second not in _NEGATION_SKIP
            and second not in _FILLER_WORDS
        ):
            end = match.end("w2")
        words.append(raw[match.start("w1") : end])
        mask.take(match.start(), end)
    if words:
        draft.exclude_keywords = _coerce_excludes(words)


def _place_value(raw: str, match: re.Match[str], require_capital: bool) -> str | None:
    """The matched place in its original spelling, or None if it is no place."""
    try:
        place = match.group("place")
    except IndexError:
        return None
    if not place:
        return None
    start, end = match.span("place")
    original = raw[start:end]
    if require_capital and not original[:1].isupper():
        return None
    return _clean_text(original, MAX_LOCATION_CHARS)


def _extract_distance(raw: str, low: str, mask: _Mask, draft: RuleDraft) -> None:
    """"100 km um Worms" -> place + radius; "Umkreis 50 km" -> radius only."""
    for pattern in _DISTANCE_RES:
        for match in pattern.finditer(low):
            if not mask.free(*match.span()):
                continue
            km = _coerce_distance(match.group("km"))
            if km is None:
                continue
            draft.max_distance_km = km
            place = _place_value(raw, match, require_capital=False)
            if place and draft.location is None:
                draft.location = place
                draft.zip_code = _coerce_zip(place)
            mask.take(*match.span())
            return


def _extract_location(raw: str, low: str, mask: _Mask, draft: RuleDraft) -> None:
    if draft.location:
        return
    for pattern, require_capital in _LOCATION_RES:
        for match in pattern.finditer(low):
            if not mask.free(*match.span()):
                continue
            place = _place_value(raw, match, require_capital)
            if not place:
                continue
            draft.location = place
            draft.zip_code = _coerce_zip(place)
            mask.take(*match.span())
            return


def _extract_zip(low: str, mask: _Mask, draft: RuleDraft) -> None:
    """A lone five-digit group is a postcode (units were claimed before)."""
    if draft.zip_code:
        return
    for match in re.finditer(r"\b(\d{5})\b(?!\s*(?:km|tkm|€|euro|eur))", low):
        if not mask.free(*match.span()):
            continue
        draft.zip_code = _coerce_zip(match.group(1))
        if draft.zip_code and not draft.location:
            draft.location = draft.zip_code
        mask.take(*match.span())
        return


def _extract_mileage(low: str, mask: _Mask, draft: RuleDraft) -> None:
    for match in _MILEAGE_RE.finditer(low):
        if not mask.free(*match.span()):
            continue
        # "tkm" and "k km" both say thousands of kilometres.
        unit = (match.group("unit") or "").replace(" ", "")
        value = _amount(match.group("num"), thousands=unit in {"tkm", "kkm"})
        km = _coerce_mileage(value)
        if km is None:
            continue
        draft.max_mileage_km = km
        mask.take(*match.span())
        return


def _extract_year(low: str, mask: _Mask, draft: RuleDraft) -> None:
    """Baujahr/Erstzulassung ab."""
    for match in _YEAR_RE.finditer(low):
        if not mask.free(*match.span()):
            continue
        year = _coerce_year(match.group("year") or match.group("year2"))
        if year is None:
            continue
        draft.min_year = year
        mask.take(*match.span())
        return


def _extract_prices(low: str, mask: _Mask, draft: RuleDraft) -> None:
    for pattern in _RANGE_RES:
        for match in pattern.finditer(low):
            if not mask.free(*match.span()):
                continue
            low_value = _amount(match.group("a"), thousands=bool(match.group("ka")))
            high_value = _amount(match.group("b"), thousands=bool(match.group("kb")))
            if low_value is None or high_value is None:
                continue
            draft.min_price, draft.max_price = sorted((low_value, high_value))
            mask.take(*match.span())
            return

    for pattern, attribute in (
        (_MAX_PRICE_RE, "max_price"),
        (_MIN_PRICE_RE, "min_price"),
        (_BARE_PRICE_RE, "max_price"),
        (_K_PRICE_RE, "max_price"),
    ):
        if getattr(draft, attribute) is not None:
            continue
        for match in pattern.finditer(low):
            if not mask.free(*match.span()):
                continue
            value = _amount(match.group("num"), thousands=bool(match.group("k")))
            if value is None:
                continue
            setattr(draft, attribute, value)
            mask.take(*match.span())
            break


def _extract_condition(low: str, mask: _Mask, draft: RuleDraft) -> None:
    for pattern, condition in _CONDITION_RES:
        for match in pattern.finditer(low):
            if not mask.free(*match.span()):
                continue
            draft.condition = condition
            mask.take(*match.span())
            return


def _extract_keywords(remaining: str) -> str:
    """What is left after every filter was cut out — the search words."""
    words: list[str] = []
    for chunk in re.split(r"[^\w\-+&/']+", remaining, flags=re.UNICODE):
        token = chunk.strip(" -_.,")
        if not token:
            continue
        if token.lower() in _FILLER_WORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        words.append(token)
        if len(words) >= 12:
            break
    return " ".join(words)[:MAX_KEYWORDS_CHARS]


# --- Optional AI refinement --------------------------------------------------
#: The only keys we read back. Anything else a model invents is dropped before
#: a single value is looked at.
_AI_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "keywords",
        "min_price",
        "max_price",
        "exclude_keywords",
        "location",
        "zip_code",
        "max_distance_km",
        "condition",
        "max_mileage_km",
        "min_year",
    }
)

_AI_SYSTEM_PROMPT = (
    "You convert a German second-hand marketplace search, written in one "
    "sentence, into structured filters. Respond ONLY with a compact JSON "
    "object, no prose, no code fences, using exactly these keys: "
    '{"name": short German label, "keywords": search words only (no prices, '
    'no places, no negations), "min_price": number or null, "max_price": '
    'number or null, "exclude_keywords": array of single German words, '
    '"location": German town or null, "zip_code": five digits or null, '
    '"max_distance_km": number or null, "condition": one of '
    '["any","new","like_new","used","defective","refurbished"], '
    '"max_mileage_km": number or null, "min_year": 4-digit year or null}. '
    "Prices are euros. Use null when the sentence does not say."
)


def _json_object(text: str) -> dict[str, Any] | None:
    """Parse a model answer into a dict — tolerant of fences, never raising."""
    payload = (text or "").strip()
    if not payload:
        return None
    if payload.startswith("```"):
        payload = payload.strip("`")
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(payload[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        logger.debug("NL rules: model answer was not JSON: {!r}", payload[:200])
        return None
    return data if isinstance(data, dict) else None


async def _ai_fields(text: str) -> dict[str, Any] | None:
    """One model call, raw dict back (no validation yet).

    The SDK is spoken to in exactly one place (:func:`app.services.ai.ask`), so
    model, timeout and failure semantics cannot drift apart between the two
    features that use it.
    """
    answer = await ai.ask(
        _AI_SYSTEM_PROMPT, text, max_tokens=500, timeout=AI_TIMEOUT_SECONDS
    )
    return _json_object(answer) if answer else None


def merge_ai_fields(draft: RuleDraft, data: Any) -> RuleDraft:
    """Fill the gaps of ``draft`` with validated model values.

    Fill-only by design: a value the deterministic parser found is never
    overwritten, so the AI can add but never silently contradict. Every value
    goes through the same coercers as the regex path, and unknown keys are
    dropped before anything is read.
    """
    if not isinstance(data, dict):
        return draft
    fields = {key: value for key, value in data.items() if key in _AI_KEYS}
    if not fields:
        return draft

    used = False
    if not draft.keywords:
        keywords = _clean_text(fields.get("keywords"), MAX_KEYWORDS_CHARS)
        if keywords:
            draft.keywords = keywords
            used = True
    if draft.min_price is None:
        value = _coerce_price(fields.get("min_price"))
        if value is not None:
            draft.min_price = value
            used = True
    if draft.max_price is None:
        value = _coerce_price(fields.get("max_price"))
        if value is not None:
            draft.max_price = value
            used = True
    if not draft.exclude_keywords:
        words = _coerce_excludes(fields.get("exclude_keywords"))
        if words:
            draft.exclude_keywords = words
            used = True
    if not draft.location:
        place = _clean_text(fields.get("location"), MAX_LOCATION_CHARS)
        if place:
            draft.location = place
            used = True
    if not draft.zip_code:
        code = _coerce_zip(fields.get("zip_code"))
        if code:
            draft.zip_code = code
            used = True
    if draft.max_distance_km is None:
        km = _coerce_distance(fields.get("max_distance_km"))
        if km is not None:
            draft.max_distance_km = km
            used = True
    if draft.condition is Condition.ANY:
        condition = _coerce_condition(fields.get("condition"))
        if condition is not Condition.ANY:
            draft.condition = condition
            used = True
    if draft.min_year is None:
        year = _coerce_year(fields.get("min_year"))
        if year is not None:
            draft.min_year = year
            used = True
    if draft.max_mileage_km is None:
        mileage = _coerce_mileage(fields.get("max_mileage_km"))
        if mileage is not None:
            draft.max_mileage_km = mileage
            used = True

    if used:
        draft.source = SOURCE_AI
    return _finalize(draft)


async def refine_with_ai(text: str, draft: RuleDraft) -> RuleDraft:
    """Optional second pass. Returns ``draft`` unchanged on any problem."""
    if not ai.is_available():
        logger.debug("NL rules: AI unavailable, keeping the deterministic draft")
        return draft
    try:
        data = await _ai_fields(text[:MAX_INPUT_CHARS])
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - AI must never break the command
        logger.warning("NL rules: AI refinement failed ({}), using regex result", exc)
        return draft
    if not data:
        return draft
    try:
        return merge_ai_fields(draft, data)
    except Exception as exc:  # noqa: BLE001 - a bad answer is not a bug report
        logger.warning("NL rules: unusable AI answer ({}), using regex result", exc)
        return draft


async def build_draft(text: str, *, use_ai: bool = True) -> RuleDraft:
    """The entry point for the bot: rules first, AI only to fill the gaps."""
    draft = parse_rule_text(text)
    if use_ai:
        draft = await refine_with_ai(text, draft)
    return draft
