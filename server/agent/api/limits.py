"""Request body size limits, enforced while the body streams in (before any parsing)."""

from __future__ import annotations

from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# /pair is the only unauthenticated route, so it gets a tight limit. The largest legitimate
# body elsewhere is an SMS batch (500 messages of up to 2000 characters).
PAIR_LIMIT = 4 * 1024
DEFAULT_LIMIT = 8 * 1024 * 1024


class BodySizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        limit = PAIR_LIMIT if scope.get("path") == "/pair" else DEFAULT_LIMIT
        headers: dict[bytes, bytes] = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await _reject(send)
            return
        seen = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    # Answer now and end the body: the app sees a disconnect (FastAPI would turn
                    # an exception here into a 400), and whatever it then sends is dropped.
                    rejected = True
                    if not started:
                        await _reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self._app(scope, limited_receive, guarded_send)


async def _reject(send: Send) -> None:
    body = b'{"detail":"request body too large"}'
    start: dict[str, Any] = {
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json"), (b"content-length", b"%d" % len(body))],
    }
    await send(start)
    await send({"type": "http.response.body", "body": body})
