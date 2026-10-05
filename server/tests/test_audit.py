from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from agent.core.audit import GENESIS_HASH, AuditLog
from agent.store.db import Database


def _setup() -> tuple[Database, AuditLog]:
    db = Database(":memory:")
    return db, AuditLog(db, lambda: datetime(2026, 10, 5, 12, 0, tzinfo=UTC))


def test_chain_verifies() -> None:
    db, audit = _setup()
    assert audit.verify()
    audit.record("proposed", actor="agent", action_id="a1")
    audit.record("approved", actor="device:d1", action_id="a1", detail="ok")
    rows = db.query("SELECT * FROM audit_log ORDER BY seq")
    assert rows[0]["prev_hash"] == GENESIS_HASH
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert audit.verify()


def test_update_and_delete_are_blocked() -> None:
    db, audit = _setup()
    audit.record("proposed", actor="agent")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE audit_log SET detail='x'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM audit_log")


def test_wrong_hash_row_fails_verification() -> None:
    db, audit = _setup()
    audit.record("proposed", actor="agent")
    db.execute(
        "INSERT INTO audit_log (ts, event, actor, action_id, detail, prev_hash, hash) "
        "VALUES ('t', 'forged', 'x', NULL, '', ?, ?)",
        (GENESIS_HASH, "f" * 64),
    )
    assert not audit.verify()


def test_record_inside_transaction() -> None:
    db, audit = _setup()
    with db.transaction():
        audit.record("a", actor="x")
        audit.record("b", actor="x")
    assert len(db.query("SELECT * FROM audit_log")) == 2
    assert audit.verify()
