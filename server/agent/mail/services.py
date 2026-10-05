"""Wiring helpers shared by the app factory and the entry point."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from agent.connectors.gmail import GmailApi
from agent.connectors.gmail_google import GmailNotConfigured
from agent.mail.store import MailStore
from agent.mail.sync import MailSync

ApiFor = Callable[[str], GmailApi]


@dataclass(frozen=True)
class MailServices:
    store: MailStore
    sync: MailSync
    api_for: ApiFor


def cached_api_factory(accounts: Iterable[str], build: ApiFor) -> ApiFor:
    """One API client per configured account, built on first use. Other accounts are refused."""
    allowed = frozenset(accounts)
    cache: dict[str, GmailApi] = {}
    guard = threading.Lock()

    def api_for(account: str) -> GmailApi:
        if account not in allowed:
            raise GmailNotConfigured("account is not configured")
        with guard:
            if account not in cache:
                cache[account] = build(account)
            return cache[account]

    return api_for
