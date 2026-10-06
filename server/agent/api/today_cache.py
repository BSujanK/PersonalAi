"""Cache behind GET /today, refreshed by a background job so a request never waits on Google.

Each source is computed outside the lock and swapped in under it. A failed refresh keeps the
last good data and only flags it. Failures are logged by exception type: the text can carry
content."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent.core.clock import Clock
from agent.core.tools import ToolKind, ToolRegistry
from agent.mail.digest import build_digest
from agent.mail.store import MailStore

log = logging.getLogger(__name__)

MAIL = "mail"
DEADLINES = "deadlines"
EVENTS = "events"
SOURCES = (MAIL, DEADLINES, EVENTS)

DIGEST_HOURS = 24
_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    DEADLINES: ("classroom_coursework", {"days": 7}),
    EVENTS: ("calendar_events", {"days": 2, "limit": 20}),
}


@dataclass(frozen=True)
class SourceState:
    data: Any = None
    has_data: bool = False
    updated_at: datetime | None = None
    failed: bool = False


class TodayCache:
    def __init__(self, registry: ToolRegistry, mail_store: MailStore | None, clock: Clock) -> None:
        self._registry = registry
        self._mail_store = mail_store
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, SourceState] = {}

    def _loader(self, source: str) -> Callable[[], Any] | None:
        """How to compute ``source``, or ``None`` while it is not configured."""
        if source == MAIL:
            store = self._mail_store
            if store is None:
                return None
            return lambda: build_digest(store, self._clock(), DIGEST_HOURS).to_json()
        name, args = _TOOLS[source]
        tool = self._registry.get(name)
        if tool is None or tool.kind is not ToolKind.READ:
            return None
        run = tool.run
        return lambda: run(dict(args))

    def refresh(self) -> None:
        self._refresh(SOURCES)

    def refresh_mail(self) -> None:
        self._refresh((MAIL,))

    def _refresh(self, sources: Iterable[str]) -> None:
        for source in sources:
            load = self._loader(source)
            if load is None:
                continue
            try:
                data = load()
            except Exception as exc:  # one broken source must not hide the others
                log.warning("today: %s refresh failed: %s", source, type(exc).__name__)
                with self._lock:
                    old = self._states.get(source, SourceState())
                    self._states[source] = SourceState(
                        old.data, old.has_data, old.updated_at, failed=True
                    )
                continue
            state = SourceState(data, True, self._clock(), failed=False)
            with self._lock:
                self._states[source] = state

    def snapshot(self) -> dict[str, SourceState]:
        """Each configured source's last state (a never-refreshed one is an empty state)."""
        configured = [s for s in SOURCES if self._loader(s) is not None]
        with self._lock:
            return {s: self._states.get(s, SourceState()) for s in configured}
