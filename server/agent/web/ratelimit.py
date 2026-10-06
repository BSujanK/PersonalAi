"""A thread-safe sliding-window rate limit."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimit:
    """At most ``max_events`` acquisitions in any ``window_seconds`` window."""

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_events
        self._window = window_seconds
        self._monotonic = monotonic
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        now = self._monotonic()
        with self._lock:
            while self._events and now - self._events[0] >= self._window:
                self._events.popleft()
            if len(self._events) >= self._max:
                return False
            self._events.append(now)
            return True
