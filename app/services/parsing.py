"""Small text-parsing helpers shared by bot handlers (kept aiogram-free so
they are unit-testable without the Telegram stack)."""

from __future__ import annotations

import re


def parse_price_range(raw: str) -> tuple[float | None, float | None] | None:
    """Parse a user-entered price or price range.

    Accepted forms (currency signs/spaces ignored):
      - ``"1200"``      -> (None, 1200)     plain number = maximum
      - ``"500-1200"``  -> (500, 1200)
      - ``"ab 500"``    -> (500, None)
      - ``"bis 1200"``  -> (None, 1200)

    Returns ``None`` if nothing numeric could be parsed.
    """
    text = raw.lower().replace("€", "").replace(",", ".").strip()
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
