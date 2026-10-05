"""Per-account client caches shared by the Google connectors."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from agent.connectors.google_auth import GoogleNotConfigured


def cached_factory[T](accounts: Iterable[str], build: Callable[[str], T]) -> Callable[[str], T]:
    """One client per configured account, built on first use. Other accounts are refused."""
    allowed = frozenset(accounts)
    cache: dict[str, T] = {}
    guard = threading.Lock()

    def client_for(account: str) -> T:
        if account not in allowed:
            raise GoogleNotConfigured("account is not configured")
        with guard:
            if account not in cache:
                cache[account] = build(account)
            return cache[account]

    return client_for
