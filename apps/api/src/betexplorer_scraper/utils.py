from __future__ import annotations

import re

_SPACE_RE = re.compile(r"\s+")


def normalize_bookmaker_name(name: str) -> str:
    cleaned = _SPACE_RE.sub(" ", name.strip()).lower()
    return cleaned.replace("&amp;", "&")


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
