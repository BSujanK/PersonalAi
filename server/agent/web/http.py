"""Shared response handling for the web clients."""

from __future__ import annotations

import httpx

from agent.web.errors import WebTooLarge

TIMEOUT_SECONDS = 15


def read_capped(
    response: httpx.Response, cap: int, *, truncate: bool = False
) -> tuple[bytes, bool]:
    """The body, read while streaming and never past ``cap`` bytes.

    Over the cap this raises ``WebTooLarge``, or with ``truncate`` stops reading and returns
    what was read, with ``True``.
    """
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > cap:
            if not truncate:
                raise WebTooLarge("response is larger than the size cap")
            return bytes(body[:cap]), True
    return bytes(body), False
