"""When each background source last completed successfully, and why its latest run failed.

Read by ``agent doctor``. A source is only recorded OK when it really did its job; a run that
failed for every account is recorded as a failure with a short reason, never as OK.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from agent.core.clock import Clock
from agent.store.db import Database

SMS_INGEST = "sms_ingest"
CLASSROOM = "classroom"
MAIL = "mail"

_REASON_LIMIT = 200
_UNSAFE = re.compile(r"[^\w .,:;()/=+-]")


@dataclass(frozen=True)
class Failure:
    at: datetime
    reason: str
    partial: bool  # some accounts still worked; the others failed


def record_ok(db: Database, name: str, clock: Clock) -> None:
    """A fully good run: records the time and clears any earlier failure."""
    with db.transaction():
        _stamp_ok(db, name, clock)
        db.execute("DELETE FROM sync_failures WHERE name = ?", (name,))


def _stamp_ok(db: Database, name: str, clock: Clock) -> None:
    db.execute(
        "INSERT INTO sync_status (name, last_ok_at) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET last_ok_at = excluded.last_ok_at",
        (name, clock().isoformat()),
    )


def record_failure(
    db: Database, name: str, clock: Clock, reason: str, *, partial: bool = False
) -> None:
    """Remember why the latest run failed. ``reason`` must name types and counts, never content."""
    safe = " ".join(_UNSAFE.sub("", reason).split())[:_REASON_LIMIT] or "failed"
    db.execute(
        "INSERT INTO sync_failures (name, failed_at, reason, partial) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET failed_at = excluded.failed_at, "
        "reason = excluded.reason, partial = excluded.partial",
        (name, clock().isoformat(), safe, int(partial)),
    )


def describe_failures(total: int, failures: Sequence[str]) -> str:
    """``"2 of 3 accounts failed: GoogleNotConfigured, HttpError"`` from exception type names."""
    kinds = ", ".join(sorted(set(failures)))
    return f"{len(failures)} of {total} account(s) failed: {kinds}"


def record_scan(
    db: Database, name: str, clock: Clock, *, succeeded: int, failures: Sequence[str]
) -> None:
    """Record a per-account run. OK needs at least one account to have worked.

    ``failures`` holds the exception type name of each account that failed. If every account
    failed, only the failure is recorded (the old OK time stays, so the check reads as failing);
    if just some did, the run counts as OK but the failure is kept as a partial one.
    """
    if succeeded > 0:
        with db.transaction():
            _stamp_ok(db, name, clock)
            db.execute("DELETE FROM sync_failures WHERE name = ?", (name,))
            if failures:
                record_failure(
                    db,
                    name,
                    clock,
                    describe_failures(succeeded + len(failures), failures),
                    partial=True,
                )
    elif failures:
        record_failure(db, name, clock, describe_failures(len(failures), failures))


def last_ok(db: Database, name: str) -> datetime | None:
    rows = db.query("SELECT last_ok_at FROM sync_status WHERE name = ?", (name,))
    return datetime.fromisoformat(rows[0]["last_ok_at"]) if rows else None


def last_failure(db: Database, name: str) -> Failure | None:
    rows = db.query("SELECT failed_at, reason, partial FROM sync_failures WHERE name = ?", (name,))
    if not rows:
        return None
    row = rows[0]
    return Failure(datetime.fromisoformat(row["failed_at"]), row["reason"], bool(row["partial"]))
