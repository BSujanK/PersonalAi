"""Tavily search client. The API key is read from the keyring on every call and sent only in the
Authorization header; neither the query, the result URLs nor the key is ever logged."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from agent.web.errors import MissingKey, WebHttpError, WebParseError
from agent.web.http import TIMEOUT_SECONDS, read_capped
from agent.web.text import flat
from agent.web.urls import validate_web_url

SEARCH_URL = "https://api.tavily.com/search"
MAX_RESPONSE_BYTES = 1024 * 1024
TITLE_CHARS = 200
SNIPPET_CHARS = 500


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class TavilyClient:
    def __init__(
        self,
        get_key: Callable[[], str | None],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._get_key = get_key
        self._transport = transport

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Raises ``MissingKey`` without a key and a ``WebError`` for HTTP, size or parse errors."""
        key = self._get_key()
        if not key:
            raise MissingKey("the Tavily API key is not set")
        body = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        with (
            httpx.Client(
                follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=self._transport
            ) as client,
            client.stream(
                "POST", SEARCH_URL, json=body, headers={"Authorization": f"Bearer {key}"}
            ) as response,
        ):
            if response.status_code != 200:
                raise WebHttpError("the search service returned an error")
            raw, _ = read_capped(response, MAX_RESPONSE_BYTES)
        return _parse(raw)[:max_results]


def _parse(raw: bytes) -> list[SearchResult]:
    try:
        data = json.loads(raw)
    except ValueError:
        raise WebParseError("the search response was not JSON") from None
    items = data.get("results") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise WebParseError("the search response had no results list")
    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        try:
            validate_web_url(url)
        except ValueError:
            continue
        results.append(
            SearchResult(
                flat(item.get("title"), TITLE_CHARS),
                url,
                flat(item.get("content"), SNIPPET_CHARS),
            )
        )
    return results
