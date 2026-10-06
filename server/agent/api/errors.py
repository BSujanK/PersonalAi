"""Logs unhandled request exceptions and 5xx responses, so a failure leaves a trace in agent.log.

Only the method, the route template (``/mail/{account}/{message_id}``, never the real path or
query), the status and the exception type are logged: exception text, headers and bodies can
carry mail content or addresses."""

from __future__ import annotations

import logging
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("agent.api")

_FORMAT = "request failed: method=%s route=%s status=%d exc=%s"
_BODY = b'{"detail":"internal_error"}'


def _route_template(scope: Scope) -> str:
    """The matched route's path template; ``unmatched`` when the router did not match one."""
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else "unmatched"


class ErrorLog:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        status = 0

        async def tracking_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, tracking_send)
        except Exception as exc:
            started = status != 0
            log.error(
                _FORMAT,
                scope.get("method", "?"),
                _route_template(scope),
                status if started else 500,
                type(exc).__name__,
            )
            if started:
                raise
            await _internal_error(send)
            return
        if status >= 500:
            log.warning(_FORMAT, scope.get("method", "?"), _route_template(scope), status, "none")


async def _internal_error(send: Send) -> None:
    start: dict[str, Any] = {
        "type": "http.response.start",
        "status": 500,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", b"%d" % len(_BODY)),
        ],
    }
    await send(start)
    await send({"type": "http.response.body", "body": _BODY})
