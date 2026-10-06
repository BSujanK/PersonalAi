"""Flattening of text that came from the internet."""

from __future__ import annotations

from agent.connectors.gmail import html_to_text
from agent.core.textutil import one_line


def flat(raw: object, limit: int) -> str:
    """One line of plain text of at most ``limit`` characters: markup stripped (twice, for
    entity-encoded tags), whitespace collapsed, control and format characters removed."""
    if not isinstance(raw, str):
        return ""
    return one_line(html_to_text(html_to_text(raw)), limit)
