"""Wiring helpers shared by the app factory and the entry point."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from agent.connectors.accounts import cached_factory
from agent.connectors.gmail import GmailApi
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
    return cached_factory(accounts, build)
