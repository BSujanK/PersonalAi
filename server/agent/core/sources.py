"""Web sources behind an answer: the pages the agent actually read or was shown by a web tool.

Sources are taken only from the raw results of the three web READ tools, never from model text,
so the model cannot make the phone show a link it invented. They are public URLs and a one-line
title; nothing else from a result is kept, and neither is ever logged.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urldefrag, urlsplit

from pydantic import BaseModel

from agent.core.textutil import one_line

MAX_SOURCES = 5
TITLE_MAX = 120
URL_MAX = 2000
_SOURCE_TOOLS = frozenset({"web_read", "web_search", "hf_models"})


class Source(BaseModel):
    title: str
    url: str


def _clean_url(value: object) -> tuple[str, str] | None:
    """The url without its fragment and its host, or ``None`` unless it is a plain http(s) url."""
    if not isinstance(value, str) or len(value) > URL_MAX:
        return None
    if any(ch.isspace() for ch in value) or one_line(value, URL_MAX) != value:
        return None
    url = urldefrag(value)[0]
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return None
    return url, host


class SourceCollector:
    """Gathers candidate sources over one turn; ``top`` ranks them: pages read, then search
    results, then Hugging Face models, de-duplicated by url, at most ``MAX_SOURCES``."""

    def __init__(self) -> None:
        self._pages: list[tuple[object, object]] = []
        self._searches: list[tuple[object, object]] = []
        self._models: list[tuple[object, object]] = []

    def add(self, tool: str, result: Any) -> None:
        """Take the sources out of one raw tool result; results of other tools are ignored."""
        if tool not in _SOURCE_TOOLS or not isinstance(result, dict) or "error" in result:
            return
        if tool == "web_read":
            self._pages.append((result.get("url"), result.get("title")))
        elif tool == "web_search":
            for item in _dicts(result.get("results")):
                self._searches.append((item.get("url"), item.get("title")))
        else:
            for item in _dicts(result.get("models")):
                self._models.append((item.get("url"), item.get("id")))

    def top(self) -> list[Source]:
        sources: list[Source] = []
        seen: set[str] = set()
        for raw_url, raw_title in (*self._pages, *self._searches, *self._models):
            cleaned = _clean_url(raw_url)
            if cleaned is None or cleaned[0] in seen:
                continue
            url, host = cleaned
            seen.add(url)
            sources.append(Source(title=one_line(raw_title, TITLE_MAX, host), url=url))
            if len(sources) == MAX_SOURCES:
                break
        return sources


def _dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
