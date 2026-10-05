"""Append-only, hash-chained audit log. Never record payloads or PII in ``detail``."""

from __future__ import annotations

import hashlib
import json

from agent.core.clock import Clock
from agent.store.db import Database

GENESIS_HASH = "0" * 64


def _compute_hash(
    prev_hash: str, ts: str, event: str, actor: str, action_id: str | None, detail: str
) -> str:
    body = json.dumps(
        {"ts": ts, "event": event, "actor": actor, "action_id": action_id, "detail": detail},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(f"{prev_hash}|{body}".encode()).hexdigest()


class AuditLog:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def record(
        self, event: str, *, actor: str, action_id: str | None = None, detail: str = ""
    ) -> None:
        ts = self._clock().isoformat()
        with self._db.transaction():
            rows = self._db.query("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
            prev = rows[0]["hash"] if rows else GENESIS_HASH
            digest = _compute_hash(prev, ts, event, actor, action_id, detail)
            self._db.execute(
                "INSERT INTO audit_log (ts, event, actor, action_id, detail, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, event, actor, action_id, detail, prev, digest),
            )

    def verify(self) -> bool:
        prev = GENESIS_HASH
        for row in self._db.query("SELECT * FROM audit_log ORDER BY seq"):
            if row["prev_hash"] != prev:
                return False
            expected = _compute_hash(
                prev, row["ts"], row["event"], row["actor"], row["action_id"], row["detail"]
            )
            if row["hash"] != expected:
                return False
            prev = row["hash"]
        return True
