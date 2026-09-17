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


#: A four-digit number in this range is a registration year, not a mileage.
#: Nobody filters for "cars under 2.018 km", and everybody writes "ab 2018".
_YEAR_MIN, _YEAR_MAX = 1950, 2100
#: Beyond this a "kilometre" bound stops meaning anything.
_MILEAGE_MAX = 2_000_000


def parse_vehicle_bounds(raw: str) -> tuple[int | None, int | None] | None:
    """Parse "max kilometres" and "registration year from" out of one line.

    Accepted forms (German thousands dots tolerated):
      - ``"100000"`` / ``"100.000 km"``   -> (100000, None)
      - ``"100000 2018"``                 -> (100000, 2018)
      - ``"2018"``                        -> (None, 2018)     a year, not a mileage
      - ``"ab 2018"``                     -> (None, 2018)

    Which number is which is decided by size, not by order: a four-digit value
    inside the year range is a year. Returns ``None`` when nothing usable was
    found, so the caller can ask again instead of storing a filter the user did
    not mean.
    """
    text = _normalize_numbers(raw)
    if not text:
        return None
    values = [int(float(m)) for m in re.findall(r"\d+(?:\.\d+)?", text)]
    if not values:
        return None

    mileage: int | None = None
    year: int | None = None
    for value in values:
        if _YEAR_MIN <= value <= _YEAR_MAX and year is None:
            year = value
        elif 0 < value <= _MILEAGE_MAX and mileage is None:
            mileage = value
    if mileage is None and year is None:
        return None
    return mileage, year
