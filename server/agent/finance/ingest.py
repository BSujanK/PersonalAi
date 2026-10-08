"""SMS batches from the phone and bank alert emails from mail sync. Logs counts only."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from agent.connectors.gmail import MailMessage
from agent.finance.ledger import Ledger
from agent.finance.model import NOTIFICATION_SENDERS, Bank, Parsed, ParsedBalance, ParsedTxn
from agent.finance.store import FinanceStore, SmsStatus, Source

log = logging.getLogger(__name__)

ParseSms = Callable[[str, str], Parsed | None]
BankForSender = Callable[[str], Bank | None]
ParseAlertEmail = Callable[[str, str, str], ParsedTxn | None]
AfterIngest = Callable[[], None]

_SKIPPED_LABELS = frozenset({"SPAM", "TRASH"})
# A bank SMS the parser rejected is kept (encrypted) for a later reparse, except anything that
# looks like a credential: those are never stored.
_SECRET_LIKE = re.compile(
    r"\b(?:otp|one[- ]time|verification code|security code|passcode|password|mpin|cvv|pin)\b",
    re.IGNORECASE,
)
# Earlier outcomes that a later parser version may turn into a transaction.
_REPARSABLE = frozenset({"balance", "unparsed"})


@dataclass(frozen=True)
class SmsIn:
    sender: str
    body: str
    received_at: datetime


@dataclass(frozen=True)
class IngestResult:
    accepted: int = 0
    duplicates: int = 0
    parsed: int = 0
    balances: int = 0
    ignored: int = 0
    unparsed: int = 0


class FinanceIngest:
    def __init__(
        self,
        store: FinanceStore,
        ledger: Ledger,
        parse_sms: ParseSms,
        bank_for_sender: BankForSender,
        parse_alert_email: ParseAlertEmail,
        after_ingest: AfterIngest | None = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._parse_sms = parse_sms
        self._bank_for_sender = bank_for_sender
        self._parse_alert_email = parse_alert_email
        self._after_ingest = after_ingest

    def ingest_sms_batch(self, items: list[SmsIn]) -> IngestResult:
        """Store a whole batch in one transaction: the phone drops its queue only after success."""
        duplicates = 0
        by_status: Counter[str] = Counter()
        with self._store.transaction():
            for item in items:
                received_at = item.received_at.astimezone(UTC)
                key = self._store.sms_key(item.sender, item.body, received_at)
                status = self._store.sms_status(key)
                if status is None:
                    by_status[self._tally(item, self._ingest_one(item, key, received_at))] += 1
                elif status in _REPARSABLE and self._parses_as_txn(item):
                    # A parser fix: an SMS stored as balance-only or unparsed is now a payment.
                    # The phone re-sending it upgrades the row instead of counting a duplicate.
                    self._store.delete_sms(key)
                    by_status[self._tally(item, self._ingest_one(item, key, received_at))] += 1
                else:
                    duplicates += 1
        if by_status["parsed"] or by_status["balance"]:
            self._run_after_ingest()
        return IngestResult(
            accepted=sum(by_status.values()),
            duplicates=duplicates,
            parsed=by_status["parsed"],
            balances=by_status["balance"],
            ignored=by_status["ignored"],
            unparsed=by_status["unparsed"],
        )

    @staticmethod
    def _tally(item: SmsIn, status: SmsStatus) -> SmsStatus:
        """An unreadable app notification is mostly noise (offers, reminders): it is kept for a
        reparse but counted as ignored, so it never reads as a bank-SMS parser failure."""
        if status == "unparsed" and item.sender in NOTIFICATION_SENDERS:
            return "ignored"
        return status

    def _run_after_ingest(self) -> None:
        if self._after_ingest is None:
            return
        try:
            self._after_ingest()
        except Exception as exc:  # never let follow-up work fail an ingest
            log.warning("finance after-ingest failed: %s", type(exc).__name__)

    def _parses_as_txn(self, item: SmsIn) -> bool:
        if self._bank_for_sender(item.sender) is None:
            return False
        try:
            return isinstance(self._parse_sms(item.sender, item.body), ParsedTxn)
        except Exception:  # the real ingest path logs parser failures; here it is just "no"
            return False

    def _ingest_one(self, item: SmsIn, key: str, received_at: datetime) -> SmsStatus:
        if self._bank_for_sender(item.sender) is None:
            # The sender may be a person's number: keep only the idempotency key.
            self._store.insert_sms(key, received_at, "", "ignored")
            return "ignored"
        try:
            parsed = self._parse_sms(item.sender, item.body)
        except Exception as exc:
            log.warning("sms parser failed: %s", type(exc).__name__)
            parsed = None
        source: Source = "notification" if item.sender in NOTIFICATION_SENDERS else "sms"
        if isinstance(parsed, ParsedTxn):
            txn_id, _ = self._ledger.record(parsed, received_at, source)
            self._store.insert_sms(key, received_at, item.sender, "parsed", txn_id=txn_id)
            return "parsed"
        if isinstance(parsed, ParsedBalance):
            self._ledger.record_balance(parsed, received_at, source)
            self._store.insert_sms(key, received_at, item.sender, "balance")
            return "balance"
        if _SECRET_LIKE.search(item.body):
            self._store.insert_sms(key, received_at, item.sender, "ignored")
            return "ignored"
        self._store.insert_sms(key, received_at, item.sender, "unparsed", body=item.body)
        return "unparsed"

    def ingest_email(self, msg: MailMessage) -> None:
        """Record a bank alert email as a transaction. Never raises."""
        try:
            if _SKIPPED_LABELS.intersection(msg.label_ids):
                return
            with self._store.transaction():
                if self._store.email_alert_seen(msg.account, msg.id):
                    return
                parsed = self._parse_alert_email(msg.from_addr, msg.subject, msg.body)
                if parsed is None:
                    self._store.record_email_alert(msg.account, msg.id, "ignored", None)
                    return
                occurred_at = datetime.fromtimestamp(msg.internal_date / 1000, UTC)
                txn_id, _ = self._ledger.record(parsed, occurred_at, "email")
                self._store.record_email_alert(msg.account, msg.id, "parsed", txn_id)
            self._run_after_ingest()
        except Exception as exc:
            log.warning("finance email ingest failed: %s", type(exc).__name__)
