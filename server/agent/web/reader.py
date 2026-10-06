"""Page reader behind ``web_read``: GET only, no credentials, no cookies, same-host redirects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from agent.connectors.gmail import html_to_text
from agent.web.errors import WebHttpError, WebParseError, WebRefused
from agent.web.http import TIMEOUT_SECONDS, read_capped
from agent.web.text import flat
from agent.web.urls import Resolver, check_resolves_public, default_resolver, validate_web_url

MAX_BODY_BYTES = 500 * 1024
MAX_TEXT_CHARS = 20_000
MAX_REDIRECTS = 3
TITLE_CHARS = 200
USER_AGENT = "PersonalAi-reader/1"
ACCEPT = "text/html, application/xhtml+xml, text/plain;q=0.9"
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_TEXT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TITLE_SEARCH_CHARS = 64 * 1024


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str
    title: str
    text: str
    truncated: bool


class WebReader:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = default_resolver,
    ) -> None:
        self._transport = transport
        self._resolver = resolver

    def read(self, url: str) -> Page:
        """Fetch ``url`` and return its text. Raises ``ValueError`` for a refused URL and a
        ``WebError`` for a refused redirect, content type or HTTP status."""
        current = self._checked(url)
        host = (urlsplit(current).hostname or "").lower()
        for _ in range(MAX_REDIRECTS + 1):
            # A fresh client per hop: a cookie set by one response is never sent on the next.
            with (
                httpx.Client(
                    follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=self._transport
                ) as client,
                client.stream(
                    "GET", current, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT}
                ) as response,
            ):
                if response.status_code in _REDIRECTS:
                    current = self._redirect_target(current, host, response.headers.get("location"))
                    continue
                if not 200 <= response.status_code < 300:
                    raise WebHttpError("the page returned an error status")
                return self._page(url, current, response)
        raise WebRefused("too many redirects")

    def _checked(self, url: str) -> str:
        validate_web_url(url)
        check_resolves_public(urlsplit(url).hostname or "", self._resolver)
        return url

    def _redirect_target(self, url: str, host: str, location: str | None) -> str:
        if not location:
            raise WebRefused("redirect without a location")
        target = urljoin(url, location)
        try:
            self._checked(target)
        except ValueError:
            raise WebRefused("redirect to a disallowed URL") from None
        if (urlsplit(target).hostname or "").lower() != host:
            raise WebRefused("redirect to another host")
        return target

    @staticmethod
    def _page(url: str, final_url: str, response: httpx.Response) -> Page:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in _TEXT_TYPES:
            raise WebParseError("the page is not HTML or plain text")
        raw, truncated = read_capped(response, MAX_BODY_BYTES, truncate=True)
        try:
            body = raw.decode(response.encoding or "utf-8", errors="replace")
        except LookupError:
            body = raw.decode("utf-8", errors="replace")
        title = ""
        if content_type == "text/plain":
            text = body
        else:
            found = _TITLE.search(body[:_TITLE_SEARCH_CHARS])
            title = flat(found.group(1), TITLE_CHARS) if found else ""
            text = html_to_text(body)
        if len(text) > MAX_TEXT_CHARS:
            text, truncated = text[:MAX_TEXT_CHARS], True
        return Page(url, final_url, title, text, truncated)
