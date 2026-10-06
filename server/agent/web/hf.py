"""Hugging Face model listing (public API, no key). Only the fields below are passed on."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from agent.core.textutil import one_line
from agent.web.errors import WebHttpError, WebParseError
from agent.web.http import TIMEOUT_SECONDS, read_capped

MODELS_URL = "https://huggingface.co/api/models"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SORT_FIELDS = {
    "new": "createdAt",
    "trending": "trendingScore",
    "downloads": "downloads",
    "likes": "likes",
}
_MODEL_ID = re.compile(r"[A-Za-z0-9][\w.-]*/[\w.-]+")


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class HuggingFaceClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def models(
        self, sort: str, task: str | None, author: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Models sorted newest-first by ``sort``. ``sort`` is one of ``new``, ``trending``,
        ``downloads`` and ``likes``. Raises a ``WebError`` for HTTP, size or parse errors."""
        params: dict[str, str | int] = {
            "sort": _SORT_FIELDS[sort],
            "direction": -1,
            "limit": limit,
        }
        if task:
            params["pipeline_tag"] = task
        if author:
            params["author"] = author
        with (
            httpx.Client(
                follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=self._transport
            ) as client,
            client.stream("GET", MODELS_URL, params=params) as response,
        ):
            if response.status_code != 200:
                raise WebHttpError("Hugging Face returned an error")
            raw, _ = read_capped(response, MAX_RESPONSE_BYTES)
        return _parse(raw)[:limit]


def _parse(raw: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except ValueError:
        raise WebParseError("the model list was not JSON") from None
    if not isinstance(data, list):
        raise WebParseError("the model list was not a list")
    models: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
            continue
        models.append(
            {
                "id": model_id,
                "author": one_line(item.get("author"), 100, model_id.split("/", 1)[0]),
                "created": one_line(item.get("createdAt"), 40) or None,
                "downloads": _count(item.get("downloads")),
                "likes": _count(item.get("likes")),
                "pipeline_tag": one_line(item.get("pipeline_tag"), 60) or None,
                "url": f"https://huggingface.co/{model_id}",
            }
        )
    return models
