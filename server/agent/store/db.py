"""SQLite access: one shared connection guarded by a re-entrant lock."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pairing_windows (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    payload_enc BLOB NOT NULL,
    preview_enc BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    nonce TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('pending', 'approved', 'rejected', 'executed', 'failed', 'expired')),
    decided_at TEXT,
    decided_by_device TEXT,
    result_enc BLOB,
    conversation_id TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    actor TEXT NOT NULL,
    action_id TEXT,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    redaction_map_enc BLOB
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL,
    content_enc BLOB NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self._depth = 0
        is_memory = str(path) == ":memory:"
        if not is_memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        if not is_memory:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._apply_schema()

    def _apply_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE ... COMMIT/ROLLBACK. Nested use joins the outer transaction."""
        with self._lock:
            if self._depth > 0:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            self._conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
            finally:
                self._depth = 0

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
