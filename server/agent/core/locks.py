"""Per-key mutual exclusion with bounded memory."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager


class _Entry:
    __slots__ = ("lock", "refs")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.refs = 0


class KeyedLocks:
    """One ``threading.Lock`` per key. An entry exists only while someone holds or awaits it."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def hold(self, key: str) -> AbstractContextManager[None]:
        return self._hold(key)

    @contextmanager
    def _hold(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = _Entry()
            entry.refs += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._guard:
                entry.refs -= 1
                if entry.refs == 0:
                    del self._entries[key]

    def __len__(self) -> int:
        with self._guard:
            return len(self._entries)
