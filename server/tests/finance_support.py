"""Finance test helpers: a wired in-memory environment with fake parsers. Synthetic data only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from agent.connectors.gmail import MailMessage
from agent.finance.categorize import categorize_by_rules
from agent.finance.ingest import FinanceIngest
from agent.finance.ledger import Ledger
from agent.finance.model import NOTIFICATION_SENDERS, Bank, Parsed, ParsedBalance, ParsedTxn
from agent.finance.reconcile import Reconciler
from agent.finance.store import FinanceStore
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from tests.support import START, FakeClock

KEY = bytes(range(32))
SENDER = "VM-TESTBK"
ALERT_FROM = "alerts@bank.example.com"


def txn(**kw: Any) -> ParsedTxn:
    base: dict[str, Any] = {
        "bank": "bob",
        "account_mask": "XX1234",
        "direction": "debit",
        "amount_paise": 123450,
        "channel": "upi",
        "counterparty": "Test Merchant",
        "reference": "400011112222",
        "txn_date": date(2026, 10, 5),
        "balance_paise": None,
    }
    base.update(kw)
    return ParsedTxn(**base)


def mail(message_id: str = "m1", **kw: Any) -> MailMessage:
    base: dict[str, Any] = {
        "account": "me@example.com",
        "id": message_id,
        "thread_id": "t1",
        "history_id": "1",
        "internal_date": int(START.timestamp() * 1000),
        "from_addr": ALERT_FROM,
        "from_name": "",
        "to": ("me@example.com",),
        "subject": "Alert",
        "snippet": "",
        "body": "body",
        "label_ids": ("INBOX",),
        "list_unsubscribe": False,
    }
    base.update(kw)
    return MailMessage(**base)


@dataclass
class FakeParsers:
    """SMS bodies and alert subjects map to canned results; anything else parses to None."""

    sms: dict[str, Parsed | Exception] = field(default_factory=dict)
    emails: dict[str, ParsedTxn] = field(default_factory=dict)

    def parse_sms(self, sender: str, body: str) -> Parsed | None:
        result = self.sms.get(body)
        if isinstance(result, Exception):
            raise result
        return result

    @staticmethod
    def bank_for_sender(sender: str) -> Bank | None:
        if sender in NOTIFICATION_SENDERS:
            return NOTIFICATION_SENDERS[sender]
        return "bob" if sender == SENDER else None

    def parse_alert_email(self, from_addr: str, subject: str, body: str) -> ParsedTxn | None:
        return self.emails.get(subject)


@dataclass
class FinEnv:
    db: Database
    clock: FakeClock
    store: FinanceStore
    ledger: Ledger
    ingest: FinanceIngest
    parsers: FakeParsers
    reconciler: Reconciler


def make_fin() -> FinEnv:
    db = Database(":memory:")
    clock = FakeClock()
    store = FinanceStore(db, FieldCipher(KEY), KEY, clock)
    ledger = Ledger(store, categorize_by_rules, clock)
    parsers = FakeParsers()
    reconciler = Reconciler(store, clock, 500_000)
    ingest = FinanceIngest(
        store,
        ledger,
        parsers.parse_sms,
        parsers.bank_for_sender,
        parsers.parse_alert_email,
        reconciler.run,
    )
    return FinEnv(db, clock, store, ledger, ingest, parsers, reconciler)


def at(minutes: int = 0) -> datetime:
    return START.astimezone(UTC) + timedelta(minutes=minutes)


def balance(**kw: Any) -> ParsedBalance:
    base: dict[str, Any] = {"bank": "bob", "account_mask": "XX1234", "balance_paise": 500000}
    base.update(kw)
    return ParsedBalance(**base)
