"""When each background source last completed successfully (read by ``agent doctor``)."""

from __future__ import annotations

from datetime import datetime

from agent.core.clock import Clock
from agent.store.db import Database

SMS_INGEST = "sms_ingest"
CLASSROOM = "classroom"
MAIL_PREFIX = "mail:"


def mail_status_name(account: str) -> str:
    return f"{MAIL_PREFIX}{account}"


def record_ok(db: Database, name: str, clock: Clock) -> None:
    db.execute(
        "INSERT INTO sync_status (name, last_ok_at) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET last_ok_at = excluded.last_ok_at",
        (name, clock().isoformat()),
    )
    db.execute("DELETE FROM sync_failures WHERE name = ?", (name,))


def record_failure(db: Database, name: str, reason: str, clock: Clock) -> None:
    """Remember why the latest run failed. ``reason`` holds type names and counts only."""
    db.execute(
        "INSERT INTO sync_failures (name, reason, failed_at) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET reason = excluded.reason, failed_at = excluded.failed_at",
        (name, reason, clock().isoformat()),
    )


def last_ok(db: Database, name: str) -> datetime | None:
    rows = db.query("SELECT last_ok_at FROM sync_status WHERE name = ?", (name,))
    return datetime.fromisoformat(rows[0]["last_ok_at"]) if rows else None


def last_failure(db: Database, name: str) -> tuple[datetime, str] | None:
    rows = db.query("SELECT failed_at, reason FROM sync_failures WHERE name = ?", (name,))
    return (datetime.fromisoformat(rows[0]["failed_at"]), rows[0]["reason"]) if rows else None
