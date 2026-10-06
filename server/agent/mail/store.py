"""Encrypted mail storage. Sensitive columns are AES-GCM; senders are indexed by keyed hash."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from agent.connectors.gmail import MailMessage
from agent.core.clock import Clock, utcnow
from agent.store.crypto import FieldCipher
from agent.store.db import Database

CATEGORIES = ("important", "normal", "promo", "spam")
# Inbox order: important first, unclassified between normal and promotions, spam last.
CATEGORY_RANKS = {"important": 0, "normal": 1, "promo": 3, "spam": 4}
UNCLASSIFIED_RANK = 2
_RANK_SQL = (
    "CASE category WHEN 'important' THEN 0 WHEN 'normal' THEN 1 WHEN 'promo' THEN 3 "
    "WHEN 'spam' THEN 4 ELSE 2 END"
)
CATEGORY_SOURCES = ("sender_rule", "gmail", "rule", "llm", "feedback")
_ADDR_HASH_LABEL = b"personalai/addr-hash/v1"


@dataclass(frozen=True)
class StoredMail:
    account: str
    id: str
    thread_id: str
    internal_date: int
    from_addr: str
    from_name: str
    to: tuple[str, ...]
    subject: str
    snippet: str
    body: str
    label_ids: tuple[str, ...]
    list_unsubscribe: bool
    category: str | None
    category_source: str | None
    reason: str | None
    reason_text: str | None = None


@dataclass(frozen=True)
class FeedbackItem:
    mail: StoredMail
    new_category: str


def _aad(column: str, account: str, message_id: str) -> str:
    return f"mail_messages.{column}:{account}/{message_id}"


class MailStore:
    def __init__(
        self, db: Database, cipher: FieldCipher, db_key: bytes, clock: Clock = utcnow
    ) -> None:
        self._db = db
        self._cipher = cipher
        self._subkey = hmac.new(db_key, _ADDR_HASH_LABEL, hashlib.sha256).digest()
        self._clock = clock

    def addr_hash(self, addr: str) -> str:
        return hmac.new(self._subkey, addr.strip().lower().encode(), hashlib.sha256).hexdigest()

    # --- messages -------------------------------------------------------------------------

    def upsert(self, msg: MailMessage) -> bool:
        """Insert or refresh a message, keeping its category. True when newly inserted."""
        enc = self._cipher.encrypt
        a, i = msg.account, msg.id
        values = (
            msg.thread_id,
            msg.history_id,
            msg.internal_date,
            self.addr_hash(msg.from_addr),
            enc(json.dumps([msg.from_addr, msg.from_name]), _aad("from", a, i)),
            enc(json.dumps(list(msg.to)), _aad("to", a, i)),
            enc(msg.subject, _aad("subject", a, i)),
            enc(msg.snippet, _aad("snippet", a, i)),
            enc(msg.body, _aad("body", a, i)),
            json.dumps(list(msg.label_ids)),
            int(msg.list_unsubscribe),
        )
        with self._db.transaction():
            existed = bool(
                self._db.query("SELECT 1 FROM mail_messages WHERE account = ? AND id = ?", (a, i))
            )
            self._db.execute(
                "INSERT INTO mail_messages (account, id, thread_id, history_id, internal_date, "
                "from_hash, from_enc, to_enc, subject_enc, snippet_enc, body_enc, label_ids, "
                "list_unsubscribe) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account, id) DO UPDATE SET thread_id = excluded.thread_id, "
                "history_id = excluded.history_id, internal_date = excluded.internal_date, "
                "from_hash = excluded.from_hash, from_enc = excluded.from_enc, "
                "to_enc = excluded.to_enc, subject_enc = excluded.subject_enc, "
                "snippet_enc = excluded.snippet_enc, body_enc = excluded.body_enc, "
                "label_ids = excluded.label_ids, list_unsubscribe = excluded.list_unsubscribe, "
                "deleted = 0",
                (a, i, *values),
            )
        return not existed

    def _hydrate(self, row: sqlite3.Row) -> StoredMail:
        dec = self._cipher.decrypt_str
        a, i = row["account"], row["id"]
        from_addr, from_name = json.loads(dec(row["from_enc"], _aad("from", a, i)))
        reason_blob = row["reason_enc"]
        return StoredMail(
            account=a,
            id=i,
            thread_id=row["thread_id"],
            internal_date=row["internal_date"],
            from_addr=from_addr,
            from_name=from_name,
            to=tuple(json.loads(dec(row["to_enc"], _aad("to", a, i)))),
            subject=dec(row["subject_enc"], _aad("subject", a, i)),
            snippet=dec(row["snippet_enc"], _aad("snippet", a, i)),
            body=dec(row["body_enc"], _aad("body", a, i)),
            label_ids=tuple(json.loads(row["label_ids"])),
            list_unsubscribe=bool(row["list_unsubscribe"]),
            category=row["category"],
            category_source=row["category_source"],
            reason=row["reason"],
            reason_text=dec(reason_blob, _aad("reason", a, i)) if reason_blob else None,
        )

    def get(self, account: str, message_id: str) -> StoredMail | None:
        rows = self._db.query(
            "SELECT * FROM mail_messages WHERE account = ? AND id = ?", (account, message_id)
        )
        return self._hydrate(rows[0]) if rows else None

    def get_labels(self, account: str, message_id: str) -> tuple[str, ...] | None:
        rows = self._db.query(
            "SELECT label_ids FROM mail_messages WHERE account = ? AND id = ?",
            (account, message_id),
        )
        return tuple(json.loads(rows[0]["label_ids"])) if rows else None

    def update_labels(self, account: str, message_id: str, label_ids: Iterable[str]) -> bool:
        cur = self._db.execute(
            "UPDATE mail_messages SET label_ids = ? WHERE account = ? AND id = ?",
            (json.dumps(list(label_ids)), account, message_id),
        )
        return cur.rowcount > 0

    def mark_deleted(self, account: str, message_id: str) -> bool:
        cur = self._db.execute(
            "UPDATE mail_messages SET deleted = 1 WHERE account = ? AND id = ?",
            (account, message_id),
        )
        return cur.rowcount > 0

    def set_category(
        self,
        account: str,
        message_id: str,
        category: str,
        source: str,
        reason: str,
        reason_text: str | None = None,
    ) -> bool:
        reason_enc = (
            self._cipher.encrypt(reason_text, _aad("reason", account, message_id))
            if reason_text
            else None
        )
        cur = self._db.execute(
            "UPDATE mail_messages SET category = ?, category_source = ?, reason = ?, "
            "reason_enc = ? WHERE account = ? AND id = ?",
            (category, source, reason, reason_enc, account, message_id),
        )
        return cur.rowcount > 0

    def recent(
        self,
        since_ms: int,
        *,
        account: str | None = None,
        category: str | None = None,
        limit: int,
    ) -> list[StoredMail]:
        sql = "SELECT * FROM mail_messages WHERE deleted = 0 AND internal_date >= ?"
        params: list[object] = [since_ms]
        if account is not None:
            sql += " AND account = ?"
            params.append(account)
        if category is not None:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY internal_date DESC, id LIMIT ?"
        params.append(limit)
        return [self._hydrate(r) for r in self._db.query(sql, params)]

    def unscanned_for_deadlines(self, since_ms: int, limit: int) -> list[StoredMail]:
        """Newest-first stored mail since ``since_ms`` the deadline scan has not looked at yet."""
        rows = self._db.query(
            "SELECT m.* FROM mail_messages m WHERE m.deleted = 0 AND m.internal_date >= ? "
            "AND NOT EXISTS (SELECT 1 FROM mail_deadline_scans s "
            "WHERE s.account = m.account AND s.message_id = m.id) "
            "ORDER BY m.internal_date DESC, m.id LIMIT ?",
            (since_ms, limit),
        )
        return [self._hydrate(r) for r in rows]

    def mark_deadline_scanned(self, account: str, message_id: str) -> None:
        """Record (ids only) that the deadline scan has handled this message."""
        self._db.execute(
            "INSERT INTO mail_deadline_scans (account, message_id, scanned_at) VALUES (?, ?, ?) "
            "ON CONFLICT (account, message_id) DO NOTHING",
            (account, message_id, self._clock().isoformat()),
        )

    def page(
        self,
        *,
        categories: Sequence[str] | None = None,
        before: tuple[int, int, str, str] | None = None,
        limit: int,
    ) -> list[StoredMail]:
        """Inbox order (see ``CATEGORY_RANKS``, then newest first), ``limit`` messages after the
        keyset ``before`` = (rank, internal_date, account, id). ``unclassified`` selects NULL."""
        where = ["deleted = 0"]
        params: list[object] = []
        if categories:
            named = [c for c in categories if c != "unclassified"]
            clauses = [f"category IN ({','.join('?' for _ in named)})"] if named else []
            if "unclassified" in categories:
                clauses.append("category IS NULL")
            where.append(f"({' OR '.join(clauses)})")
            params.extend(named)
        sql = f"SELECT *, {_RANK_SQL} AS rank FROM mail_messages WHERE {' AND '.join(where)}"  # noqa: S608
        if before is not None:
            rank, date, account, message_id = before
            sql = (
                f"SELECT * FROM ({sql}) WHERE rank > ? OR (rank = ? AND (internal_date < ? "  # noqa: S608
                "OR (internal_date = ? AND (account > ? OR (account = ? AND id > ?)))))"
            )
            params.extend([rank, rank, date, date, account, account, message_id])
        sql += " ORDER BY rank, internal_date DESC, account, id LIMIT ?"
        params.append(limit)
        return [self._hydrate(r) for r in self._db.query(sql, params)]

    def category_counts(self) -> dict[str, int]:
        """Every non-deleted message by category, with ``unclassified`` for those without one."""
        counts = dict.fromkeys((*CATEGORIES, "unclassified"), 0)
        for row in self._db.query(
            "SELECT category, COUNT(*) AS n FROM mail_messages WHERE deleted = 0 GROUP BY category"
        ):
            counts[row["category"] or "unclassified"] = row["n"]
        return counts

    # --- replied-to recipients ------------------------------------------------------------

    def add_replied(self, account: str, addrs: Iterable[str]) -> None:
        with self._db.transaction():
            for addr in addrs:
                self._db.execute(
                    "INSERT OR IGNORE INTO mail_replied (account, addr_hash) VALUES (?, ?)",
                    (account, self.addr_hash(addr)),
                )

    def has_replied(self, account: str, addr: str) -> bool:
        return bool(
            self._db.query(
                "SELECT 1 FROM mail_replied WHERE account = ? AND addr_hash = ?",
                (account, self.addr_hash(addr)),
            )
        )

    def sent_to_any(self, addr: str) -> bool:
        """Whether synced sent mail of any account went to ``addr``."""
        return bool(
            self._db.query(
                "SELECT 1 FROM mail_replied WHERE addr_hash = ? LIMIT 1", (self.addr_hash(addr),)
            )
        )

    # --- sender rules and feedback --------------------------------------------------------

    def sender_rule(self, addr: str) -> str | None:
        rows = self._db.query(
            "SELECT category FROM sender_rules WHERE sender_hash = ?", (self.addr_hash(addr),)
        )
        return str(rows[0]["category"]) if rows else None

    def set_sender_rule(self, addr: str, category: str, source: str) -> None:
        digest = self.addr_hash(addr)
        self._db.execute(
            "INSERT INTO sender_rules (sender_hash, sender_enc, category, created_at, source) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(sender_hash) DO UPDATE SET "
            "category = excluded.category, source = excluded.source",
            (
                digest,
                self._cipher.encrypt(addr.strip().lower(), f"sender_rules.sender:{digest}"),
                category,
                self._clock().isoformat(),
                source,
            ),
        )

    def record_feedback(
        self, account: str, message_id: str, old_category: str | None, new_category: str
    ) -> None:
        self._db.execute(
            "INSERT INTO mail_feedback (account, message_id, old_category, new_category, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (account, message_id, old_category, new_category, self._clock().isoformat()),
        )

    def recent_feedback(self, limit: int) -> list[FeedbackItem]:
        rows = self._db.query(
            "SELECT m.*, f.new_category AS fb_category FROM mail_feedback f "
            "JOIN mail_messages m ON m.account = f.account AND m.id = f.message_id "
            "ORDER BY f.id DESC LIMIT ?",
            (limit,),
        )
        return [FeedbackItem(self._hydrate(r), r["fb_category"]) for r in rows]

    # --- sync cursor ----------------------------------------------------------------------

    def get_history_id(self, account: str) -> str | None:
        rows = self._db.query("SELECT history_id FROM mail_accounts WHERE account = ?", (account,))
        return rows[0]["history_id"] if rows else None

    def set_history_id(self, account: str, history_id: str, now: str) -> None:
        self._db.execute(
            "INSERT INTO mail_accounts (account, history_id, last_sync_at) VALUES (?, ?, ?) "
            "ON CONFLICT(account) DO UPDATE SET history_id = excluded.history_id, "
            "last_sync_at = excluded.last_sync_at",
            (account, history_id, now),
        )
