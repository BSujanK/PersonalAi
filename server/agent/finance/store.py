"""Encrypted finance storage. Amounts, balances, counterparties and account masks are AES-GCM;
rows are matched through keyed hashes, and time, direction, category and channel stay plaintext
for filtering."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from agent.core.clock import Clock, utcnow
from agent.finance.model import ParsedTxn
from agent.store.crypto import FieldCipher
from agent.store.db import Database

Source = Literal["sms", "email", "notification"]
BalanceSource = Literal["sms", "email"]
SmsStatus = Literal["parsed", "balance", "ignored", "unparsed"]
CategorySource = Literal["rule", "user_rule", "llm", "user"]

UNCATEGORIZED = "uncategorized"
_ACCOUNT_LABEL = b"personalai/finance-account/v1"
_COUNTERPARTY_LABEL = b"personalai/finance-counterparty/v1"
_REFERENCE_LABEL = b"personalai/finance-reference/v1"
_SMS_LABEL = b"personalai/finance-sms/v1"


def iso(moment: datetime) -> str:
    """Fixed-width UTC timestamp, so string order is time order."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class StoredTxn:
    id: int
    bank: str
    account_mask: str | None
    direction: str
    channel: str
    amount_paise: int
    occurred_at: datetime
    counterparty: str | None
    balance_paise: int | None
    category: str | None
    category_source: str | None
    from_sms: bool
    from_email: bool
    from_notification: bool = False
    account_hash: str | None = None
    reference_hash: str | None = None
    txn_date: date | None = None
    inferred: bool = False  # an unrecorded payment worked out from a balance gap
    window_from: datetime | None = None  # inferred rows: the balance readings it lies between
    window_to: datetime | None = None


@dataclass(frozen=True)
class StoredBalance:
    bank: str
    account_mask: str
    balance_paise: int
    as_of: datetime
    source: str


def _aad(column: str, txn_id: int) -> str:
    return f"finance_txns.{column}:{txn_id}"


def _normalise_counterparty(name: str) -> str:
    return " ".join(name.lower().split())


class FinanceStore:
    def __init__(
        self, db: Database, cipher: FieldCipher, db_key: bytes, clock: Clock = utcnow
    ) -> None:
        self._db = db
        self._cipher = cipher
        self._clock = clock

        def sub(label: bytes) -> bytes:
            return hmac.new(db_key, label, hashlib.sha256).digest()

        self._account_key = sub(_ACCOUNT_LABEL)
        self._counterparty_key = sub(_COUNTERPARTY_LABEL)
        self._reference_key = sub(_REFERENCE_LABEL)
        self._sms_key = sub(_SMS_LABEL)

    def transaction(self) -> AbstractContextManager[None]:
        """Group several store calls atomically; nested use joins the outer transaction."""
        return self._db.transaction()

    # --- keyed hashes ---------------------------------------------------------------------

    @staticmethod
    def _mac(key: bytes, text: str) -> str:
        return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()

    def account_hash(self, bank: str, mask: str) -> str:
        return self._mac(self._account_key, f"{bank}|{mask.strip().upper()}")

    def counterparty_hash(self, name: str) -> str:
        return self._mac(self._counterparty_key, _normalise_counterparty(name))

    def reference_hash(self, reference: str) -> str:
        return self._mac(self._reference_key, reference.strip().upper())

    def sms_key(self, sender: str, body: str, received_at: datetime) -> str:
        # Whole seconds: the inbox scan reports 11:19:52.000 and the live receiver 11:19:52.453
        # for the same SMS; with full precision they looked like two messages.
        moment = received_at.replace(microsecond=0)
        return self._mac(self._sms_key, f"{sender}|{body}|{iso(moment)}")

    # --- SMS log --------------------------------------------------------------------------

    def sms_exists(self, key_hash: str) -> bool:
        return bool(self._db.query("SELECT 1 FROM finance_sms WHERE key_hash = ?", (key_hash,)))

    def sms_status(self, key_hash: str) -> str | None:
        rows = self._db.query("SELECT status FROM finance_sms WHERE key_hash = ?", (key_hash,))
        return str(rows[0]["status"]) if rows else None

    def delete_sms(self, key_hash: str) -> None:
        self._db.execute("DELETE FROM finance_sms WHERE key_hash = ?", (key_hash,))

    def insert_sms(
        self,
        key_hash: str,
        received_at: datetime,
        sender: str,
        status: SmsStatus,
        *,
        body: str | None = None,
        txn_id: int | None = None,
    ) -> None:
        body_enc = (
            self._cipher.encrypt(body, f"finance_sms.body:{key_hash}") if body is not None else None
        )
        self._db.execute(
            "INSERT INTO finance_sms (key_hash, received_at, sender, status, body_enc, txn_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key_hash, iso(received_at), sender, status, body_enc, txn_id),
        )

    # --- email alerts ---------------------------------------------------------------------

    def email_alert_seen(self, account: str, message_id: str) -> bool:
        return bool(
            self._db.query(
                "SELECT 1 FROM finance_email_alerts WHERE account = ? AND message_id = ?",
                (account, message_id),
            )
        )

    def record_email_alert(
        self, account: str, message_id: str, status: str, txn_id: int | None
    ) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO finance_email_alerts (account, message_id, status, txn_id) "
            "VALUES (?, ?, ?, ?)",
            (account, message_id, status, txn_id),
        )

    # --- transactions ---------------------------------------------------------------------

    def insert_txn(
        self,
        parsed: ParsedTxn,
        occurred_at: datetime,
        source: Source,
        category: tuple[str, CategorySource] | None,
    ) -> int:
        return self._insert(parsed, occurred_at, source, category, None)

    def insert_inferred(
        self,
        parsed: ParsedTxn,
        occurred_at: datetime,
        window: tuple[datetime, datetime],
        category: tuple[str, CategorySource],
    ) -> int:
        """An unrecorded payment inferred from a balance gap: no source flag is set."""
        return self._insert(parsed, occurred_at, None, category, window)

    def _insert(
        self,
        parsed: ParsedTxn,
        occurred_at: datetime,
        source: Source | None,
        category: tuple[str, CategorySource] | None,
        window: tuple[datetime, datetime] | None,
    ) -> int:
        enc = self._cipher.encrypt
        account_hash = (
            self.account_hash(parsed.bank, parsed.account_mask) if parsed.account_mask else None
        )
        counterparty = parsed.counterparty.strip() if parsed.counterparty else None
        with self._db.transaction():
            # The row id is the AAD, so it is known only after the insert.
            cur = self._db.execute(
                "INSERT INTO finance_txns (bank, account_hash, direction, channel, amount_enc, "
                "occurred_at, txn_date, counterparty_hash, reference_hash, category, "
                "category_source, from_sms, from_email, from_notification, inferred, "
                "window_from, window_to, created_at) "
                "VALUES (?, ?, ?, ?, x'', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    parsed.bank,
                    account_hash,
                    parsed.direction,
                    parsed.channel,
                    iso(occurred_at),
                    parsed.txn_date.isoformat() if parsed.txn_date else None,
                    self.counterparty_hash(counterparty) if counterparty else None,
                    self.reference_hash(parsed.reference) if parsed.reference else None,
                    category[0] if category else None,
                    category[1] if category else None,
                    int(source == "sms"),
                    int(source == "email"),
                    int(source == "notification"),
                    int(window is not None),
                    iso(window[0]) if window else None,
                    iso(window[1]) if window else None,
                    iso(self._clock()),
                ),
            )
            txn_id = int(cur.lastrowid or 0)
            self._db.execute(
                "UPDATE finance_txns SET amount_enc = ?, account_mask_enc = ?, "
                "counterparty_enc = ?, balance_enc = ? WHERE id = ?",
                (
                    enc(str(parsed.amount_paise), _aad("amount", txn_id)),
                    enc(parsed.account_mask, _aad("account_mask", txn_id))
                    if parsed.account_mask
                    else None,
                    enc(counterparty, _aad("counterparty", txn_id)) if counterparty else None,
                    enc(str(parsed.balance_paise), _aad("balance", txn_id))
                    if parsed.balance_paise is not None
                    else None,
                    txn_id,
                ),
            )
        return txn_id

    def _hydrate(self, row: sqlite3.Row) -> StoredTxn:
        dec = self._cipher.decrypt_str
        i = int(row["id"])
        mask, cp, bal = row["account_mask_enc"], row["counterparty_enc"], row["balance_enc"]
        return StoredTxn(
            id=i,
            bank=row["bank"],
            account_mask=dec(mask, _aad("account_mask", i)) if mask else None,
            direction=row["direction"],
            channel=row["channel"],
            amount_paise=int(dec(row["amount_enc"], _aad("amount", i))),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            counterparty=dec(cp, _aad("counterparty", i)) if cp else None,
            balance_paise=int(dec(bal, _aad("balance", i))) if bal else None,
            category=row["category"],
            category_source=row["category_source"],
            from_sms=bool(row["from_sms"]),
            from_email=bool(row["from_email"]),
            from_notification=bool(row["from_notification"]),
            account_hash=row["account_hash"],
            reference_hash=row["reference_hash"],
            txn_date=date.fromisoformat(row["txn_date"]) if row["txn_date"] else None,
            inferred=bool(row["inferred"]),
            window_from=datetime.fromisoformat(row["window_from"]) if row["window_from"] else None,
            window_to=datetime.fromisoformat(row["window_to"]) if row["window_to"] else None,
        )

    def get_txn(self, txn_id: int) -> StoredTxn | None:
        rows = self._db.query("SELECT * FROM finance_txns WHERE id = ?", (txn_id,))
        return self._hydrate(rows[0]) if rows else None

    def find_by_reference(self, bank: str, direction: str, reference: str) -> StoredTxn | None:
        """The stored payment with this bank reference, from any source.

        A bank reference identifies one payment: the same SMS uploaded twice, or two different
        alerts the bank sent for one payment, must not count twice.
        """
        rows = self._db.query(
            "SELECT * FROM finance_txns WHERE bank = ? AND direction = ? AND reference_hash = ? "
            "ORDER BY id LIMIT 1",
            (bank, direction, self.reference_hash(reference)),
        )
        return self._hydrate(rows[0]) if rows else None

    def find_dedup_candidates(
        self,
        direction: str,
        occurred_at: datetime,
        window: timedelta,
        reference: str | None,
        source: Source,
    ) -> list[StoredTxn]:
        """Recorded rows without this source's flag that share the reference or fall inside the
        window. Inferred rows are not payments seen by any source, so they never match."""
        flag = {"sms": "from_sms", "email": "from_email", "notification": "from_notification"}
        other = f"{flag[source]} = 0 AND inferred = 0"
        match = "(occurred_at >= ? AND occurred_at <= ?)"
        params: list[object] = [direction, iso(occurred_at - window), iso(occurred_at + window)]
        if reference:
            match += " OR reference_hash = ?"
            params.append(self.reference_hash(reference))
        rows = self._db.query(
            f"SELECT * FROM finance_txns WHERE direction = ? AND {other} AND ({match})",  # noqa: S608
            params,
        )
        return [self._hydrate(r) for r in rows]

    def merge_txn(
        self, txn_id: int, parsed: ParsedTxn, source: Source, existing: StoredTxn
    ) -> None:
        """Mark the extra source and fill fields the existing row lacks."""
        enc = self._cipher.encrypt
        flag = {"sms": "from_sms", "email": "from_email", "notification": "from_notification"}
        sets = [f"{flag[source]} = 1"]
        params: list[object] = []
        if existing.reference_hash is None and parsed.reference:
            sets.append("reference_hash = ?")
            params.append(self.reference_hash(parsed.reference))
        # A bank's own wording beats a payment app's: it replaces a notification-only name.
        app_only = existing.from_notification and not (existing.from_sms or existing.from_email)
        if (
            (existing.counterparty is None or (app_only and source != "notification"))
            and parsed.counterparty
            and parsed.counterparty.strip()
        ):
            name = parsed.counterparty.strip()
            sets += ["counterparty_enc = ?", "counterparty_hash = ?"]
            params += [enc(name, _aad("counterparty", txn_id)), self.counterparty_hash(name)]
        if existing.account_hash is None and parsed.account_mask:
            sets += ["account_hash = ?", "account_mask_enc = ?"]
            params += [
                self.account_hash(parsed.bank, parsed.account_mask),
                enc(parsed.account_mask, _aad("account_mask", txn_id)),
            ]
        if existing.balance_paise is None and parsed.balance_paise is not None:
            sets.append("balance_enc = ?")
            params.append(enc(str(parsed.balance_paise), _aad("balance", txn_id)))
        if existing.txn_date is None and parsed.txn_date:
            sets.append("txn_date = ?")
            params.append(parsed.txn_date.isoformat())
        self._db.execute(
            f"UPDATE finance_txns SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            (*params, txn_id),
        )

    def txns_between(
        self,
        start: datetime,
        end: datetime,
        *,
        direction: str | None = None,
        category: str | None = None,
        channel: str | None = None,
    ) -> list[StoredTxn]:
        """Transactions with start <= occurred_at < end, oldest first."""
        sql = "SELECT * FROM finance_txns WHERE occurred_at >= ? AND occurred_at < ?"
        params: list[object] = [iso(start), iso(end)]
        if direction is not None:
            sql += " AND direction = ?"
            params.append(direction)
        if category == UNCATEGORIZED:
            sql += " AND category IS NULL"
        elif category is not None:
            sql += " AND category = ?"
            params.append(category)
        if channel is not None:
            sql += " AND channel = ?"
            params.append(channel)
        sql += " ORDER BY occurred_at, id"
        return [self._hydrate(r) for r in self._db.query(sql, params)]

    def txns_since(self, since: datetime) -> list[StoredTxn]:
        """Every recorded and inferred row from ``since`` on, oldest first."""
        rows = self._db.query(
            "SELECT * FROM finance_txns WHERE occurred_at >= ? ORDER BY occurred_at, id",
            (iso(since),),
        )
        return [self._hydrate(r) for r in rows]

    def inferred_since(self, since: datetime) -> list[StoredTxn]:
        """Inferred rows whose window opens at or after ``since``, oldest first."""
        rows = self._db.query(
            "SELECT * FROM finance_txns WHERE inferred = 1 AND window_from >= ? "
            "ORDER BY window_from, id",
            (iso(since),),
        )
        return [self._hydrate(r) for r in rows]

    def set_inferred_amount(self, txn_id: int, amount_paise: int) -> None:
        self._db.execute(
            "UPDATE finance_txns SET amount_enc = ? WHERE id = ? AND inferred = 1",
            (self._cipher.encrypt(str(amount_paise), _aad("amount", txn_id)), txn_id),
        )

    def delete_inferred(self, txn_id: int) -> None:
        self._db.execute("DELETE FROM finance_txns WHERE id = ? AND inferred = 1", (txn_id,))

    def uncategorized(self, limit: int) -> list[StoredTxn]:
        rows = self._db.query(
            "SELECT * FROM finance_txns WHERE category IS NULL AND inferred = 0 "
            "ORDER BY id LIMIT ?",
            (limit,),
        )
        return [self._hydrate(r) for r in rows]

    def set_category(self, txn_id: int, category: str, source: CategorySource) -> bool:
        cur = self._db.execute(
            "UPDATE finance_txns SET category = ?, category_source = ? WHERE id = ?",
            (category, source, txn_id),
        )
        return cur.rowcount > 0

    # --- balances -------------------------------------------------------------------------

    def upsert_balance(
        self, bank: str, mask: str, balance_paise: int, as_of: datetime, source: BalanceSource
    ) -> bool:
        """Store the figure only when it is newer than the one held. True when stored."""
        digest = self.account_hash(bank, mask)
        stamp = iso(as_of)
        with self._db.transaction():
            rows = self._db.query(
                "SELECT as_of FROM finance_balances WHERE account_hash = ?", (digest,)
            )
            if rows and rows[0]["as_of"] >= stamp:
                return False
            self._db.execute(
                "INSERT INTO finance_balances (account_hash, bank, account_mask_enc, "
                "balance_enc, as_of, source) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account_hash) DO UPDATE SET balance_enc = excluded.balance_enc, "
                "as_of = excluded.as_of, source = excluded.source",
                (
                    digest,
                    bank,
                    self._cipher.encrypt(mask, f"finance_balances.account_mask:{digest}"),
                    self._cipher.encrypt(str(balance_paise), f"finance_balances.balance:{digest}"),
                    stamp,
                    source,
                ),
            )
        return True

    def list_balances(self) -> list[StoredBalance]:
        dec = self._cipher.decrypt_str
        out: list[StoredBalance] = []
        for r in self._db.query("SELECT * FROM finance_balances ORDER BY bank, account_hash"):
            digest = r["account_hash"]
            out.append(
                StoredBalance(
                    bank=r["bank"],
                    account_mask=dec(
                        r["account_mask_enc"], f"finance_balances.account_mask:{digest}"
                    ),
                    balance_paise=int(dec(r["balance_enc"], f"finance_balances.balance:{digest}")),
                    as_of=datetime.fromisoformat(r["as_of"]),
                    source=r["source"],
                )
            )
        return out

    # --- owner category rules -------------------------------------------------------------

    def category_rule(self, counterparty: str) -> str | None:
        rows = self._db.query(
            "SELECT category FROM finance_category_rules WHERE counterparty_hash = ?",
            (self.counterparty_hash(counterparty),),
        )
        return str(rows[0]["category"]) if rows else None

    def set_category_rule(self, counterparty: str, category: str) -> None:
        self._db.execute(
            "INSERT INTO finance_category_rules (counterparty_hash, category, created_at) "
            "VALUES (?, ?, ?) ON CONFLICT(counterparty_hash) DO UPDATE SET "
            "category = excluded.category",
            (self.counterparty_hash(counterparty), category, iso(self._clock())),
        )
