"""Small text helpers for values that end up in titles, alerts and tool results."""

from __future__ import annotations

import unicodedata

_DROPPED = frozenset({"Cc", "Cf", "Zl", "Zp"})


def one_line(value: object, limit: int, default: str = "") -> str:
    """A single line of at most ``limit`` characters: whitespace collapsed, control and format
    characters (zero-width, bidi, line separators) removed. Non-strings give ``default``."""
    if not isinstance(value, str):
        return default
    spaced = "".join(" " if ch.isspace() else ch for ch in value)
    kept = "".join(ch for ch in spaced if unicodedata.category(ch) not in _DROPPED)
    return " ".join(kept.split())[:limit].rstrip() or default
