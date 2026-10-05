"""When each background source last completed successfully (read by ``agent doctor``)."""

from __future__ import annotations

from datetime import datetime

from agent.core.clock import Clock
from agent.store.db import Database

SMS_INGEST = "sms_ingest"
CLASSROOM = "classroom"


def record_ok(db: Database, name: str, clock: Clock) -> None:
    db.execute(
        "INSERT INTO sync_status (name, last_ok_at) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET last_ok_at = excluded.last_ok_at",
        (name, clock().isoformat()),
    )


def last_ok(db: Database, name: str) -> datetime | None:
    rows = db.query("SELECT last_ok_at FROM sync_status WHERE name = ?", (name,))
    return datetime.fromisoformat(rows[0]["last_ok_at"]) if rows else None
