from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import Settings
from agent.store.db import SCHEMA_VERSION, Database


def test_schema_is_idempotent_and_versioned(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "agent.db"
    Database(path).close()
    db = Database(path)
    assert db.query("PRAGMA user_version")[0][0] == SCHEMA_VERSION
    assert db.query("PRAGMA foreign_keys")[0][0] == 1
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"


def test_transaction_commit_rollback_and_nesting() -> None:
    db = Database(":memory:")
    with db.transaction():
        db.execute("INSERT INTO conversations (id, created_at) VALUES ('c1', 't')")
        with db.transaction():
            db.execute("INSERT INTO conversations (id, created_at) VALUES ('c2', 't')")
    assert len(db.query("SELECT * FROM conversations")) == 2
    with pytest.raises(RuntimeError), db.transaction():
        db.execute("INSERT INTO conversations (id, created_at) VALUES ('c3', 't')")
        raise RuntimeError
    assert len(db.query("SELECT * FROM conversations")) == 2


def test_settings_from_env() -> None:
    s = Settings.from_env(
        {
            "PERSONALAI_BIND_HOSTS": "127.0.0.1, 100.64.0.2",
            "PERSONALAI_PORT": "9000",
            "PERSONALAI_DB_PATH": "/tmp/x.db",  # noqa: S108
            "PERSONALAI_OWNER_EMAILS": "me@example.com,",
        }
    )
    assert s.bind_hosts == ("127.0.0.1", "100.64.0.2")
    assert s.port == 9000
    assert s.owner_emails == ("me@example.com",)
    assert Settings.from_env({}).bind_hosts == ("127.0.0.1",)
