"""Content-free push (CLAUDE.md rule 7). A push says only how many approvals are pending;
the app fetches the details itself over Tailscale. Push is off unless PERSONALAI_PUSH=expo."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable

import httpx

from agent.store.db import Database
from agent.store.keystore import KeyStore

log = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
PUSH_TITLE = "PersonalAi"
TOKEN_RE = re.compile(r"Expo(?:nent)?PushToken\[[A-Za-z0-9_-]{8,128}\]")

Sender = Callable[[list[dict[str, str]]], None]


def _key(device_id: str) -> str:
    return f"push_token:{device_id}"


def pending_text(count: int) -> str:
    return f"{count} approval{'s' if count != 1 else ''} pending"


def expo_sender(messages: list[dict[str, str]]) -> None:
    httpx.post(EXPO_PUSH_URL, json=messages, timeout=10).raise_for_status()


class PushNotifier:
    def __init__(
        self,
        db: Database,
        keystore: KeyStore,
        *,
        enabled: bool,
        sender: Sender = expo_sender,
        background: bool = True,
    ) -> None:
        self._db = db
        self._keystore = keystore
        self._enabled = enabled
        self._sender = sender
        self._background = background

    def set_token(self, device_id: str, token: str) -> None:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("not an Expo push token")
        self._keystore.set(_key(device_id), token)

    def clear_token(self, device_id: str) -> None:
        self._keystore.delete(_key(device_id))

    def _tokens(self) -> list[str]:
        rows = self._db.query("SELECT id FROM devices WHERE revoked = 0")
        return [t for r in rows if (t := self._keystore.get(_key(r["id"]))) is not None]

    def notify_pending(self, count: int) -> None:
        """Send "N approvals pending" to every paired device with a push token. Never raises."""
        if not self._enabled or count < 1:
            return
        messages = [
            {"to": t, "title": PUSH_TITLE, "body": pending_text(count), "priority": "high"}
            for t in self._tokens()
        ]
        if not messages:
            return
        if self._background:
            threading.Thread(target=self._send, args=(messages,), daemon=True).start()
        else:
            self._send(messages)

    def _send(self, messages: list[dict[str, str]]) -> None:
        try:
            self._sender(messages)
        except Exception as exc:  # push is best effort; the app also polls
            log.warning("push failed: %s", type(exc).__name__)
