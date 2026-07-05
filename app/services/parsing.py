"""Small text-parsing helpers shared by bot handlers (kept aiogram-free so
they are unit-testable without the Telegram stack)."""

from __future__ import annotations

import re


def _normalize_numbers(raw: str) -> str:
    """Normalise German/international number formats in free-form user input.

    - strips currency signs
    - removes thousands separators: ``18.000`` -> ``18000``
    - converts a decimal comma to a dot: ``1200,50`` -> ``1200.50``
    - commas used as list separators become spaces: ``18000, 20000``
    """
    text = raw.lower().replace("€", " ").strip()
    # Thousands dots: a dot followed by exactly 3 digits (possibly repeated).
    text = re.sub(r"\.(?=\d{3}(?:\D|$))", "", text)
    # Decimal comma: comma followed by 1-2 digits and then a non-digit/end.
    text = re.sub(r",(?=\d{1,2}(?:\D|$))", ".", text)
    # Remaining commas separate values.
    return text.replace(",", " ")


def parse_price_range(raw: str) -> tuple[float | None, float | None] | None:
    """Parse a user-entered price or price range.

    Accepted forms (currency signs, thousands dots and spaces are tolerated):
      - ``"20000"``            -> (None, 20000)     plain number = maximum
      - ``"18000-20000"``      -> (18000, 20000)
      - ``"18000 20000"``      -> (18000, 20000)    space works like the dash
      - ``"18.000-20.000"``    -> (18000, 20000)    German thousands format
      - ``"18000, 20000"``     -> (18000, 20000)
      - ``"ab 18000"``         -> (18000, None)
      - ``"bis 20000"``        -> (None, 20000)

    Two numbers are always interpreted as (min, max); swapped bounds are
    corrected automatically. Returns ``None`` if nothing numeric was found.
    """
    text = _normalize_numbers(raw)
    if not text:
        return None

    nums = [float(m) for m in re.findall(r"\d+(?:\.\d{1,2})?", text)]
    if not nums:
        return None

    if len(nums) >= 2:
        lo, hi = nums[0], nums[1]
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)

    value = nums[0]
    if "ab" in text or text.endswith("+"):
        return (value, None)
    return (None, value)
