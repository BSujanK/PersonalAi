from __future__ import annotations

import sqlite3
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


def test_an_older_database_gains_the_mail_deadline_scan_table(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    first = Database(path)
    first.execute("DROP TABLE mail_deadline_scans")
    first.execute("PRAGMA user_version=8")
    first.close()
    db = Database(path)
    db.execute(
        "INSERT INTO mail_deadline_scans (account, message_id, scanned_at) VALUES ('a', 'm', 't')"
    )
    assert db.query("PRAGMA user_version")[0][0] == SCHEMA_VERSION


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


def test_model_settings_from_env() -> None:
    s = Settings.from_env(
        {
            "PERSONALAI_MODEL_PRIMARY": " org/primary ",
            "PERSONALAI_MODEL_FALLBACK": "org/fallback",
            "PERSONALAI_MODEL_LONG": "org/long ",
            "PERSONALAI_LONG_CONTEXT_TOKENS": "5000",
        }
    )
    assert (s.model_primary, s.model_fallback, s.model_long) == (
        "org/primary",
        "org/fallback",
        "org/long",
    )
    assert s.long_context_tokens == 5000
    d = Settings.from_env({})
    assert (d.model_primary, d.model_fallback, d.model_long) == ("", "", "")
    assert d.long_context_tokens == 32000


@pytest.mark.parametrize("value", ["0", "-5", "abc", ""])
def test_long_context_tokens_must_be_positive_int(value: str) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        Settings.from_env({"PERSONALAI_LONG_CONTEXT_TOKENS": value})


def test_mail_settings_from_env() -> None:
    s = Settings.from_env(
        {
            "PERSONALAI_OWNER_EMAILS": "Me@example.com",
            "PERSONALAI_MAIL_ACCOUNTS": "me@example.com, college@example.edu",
            "PERSONALAI_VIP_SENDERS": "mentor@example.org",
            "PERSONALAI_COLLEGE_DOMAINS": "college.example.edu",
            "PERSONALAI_MAIL_POLL_MINUTES": "10",
            "PERSONALAI_CLASSIFIER_MODEL": "tiny",
        }
    )
    assert s.mail_accounts == ("me@example.com", "college@example.edu")
    assert s.vip_senders == ("mentor@example.org",)
    assert s.college_domains == ("college.example.edu",)
    assert (s.mail_poll_minutes, s.mail_initial_days, s.classifier_model) == (10, 7, "tiny")
    assert s.redaction_emails == ("me@example.com", "college@example.edu")
    assert Settings().mail_accounts == ()


def test_messages_conversation_seq_is_unique() -> None:
    db = Database(":memory:")
    db.execute("INSERT INTO conversations (id, created_at) VALUES ('c', 't')")
    row = "INSERT INTO messages VALUES (?, 'c', 1, 't', 'user', x'00')"
    db.execute(row, ("a",))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(row, ("b",))


_V9_FINANCE_TXNS = """
CREATE TABLE finance_txns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL,
    account_hash TEXT,
    account_mask_enc BLOB,
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    channel TEXT NOT NULL,
    amount_enc BLOB NOT NULL,
    occurred_at TEXT NOT NULL,
    txn_date TEXT,
    counterparty_enc BLOB,
    counterparty_hash TEXT,
    reference_hash TEXT,
    balance_enc BLOB,
    category TEXT,
    category_source TEXT CHECK (category_source IN ('rule', 'user_rule', 'llm', 'user')),
    from_sms INTEGER NOT NULL DEFAULT 0,
    from_email INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


def test_a_v9_database_gains_the_notification_and_inferred_columns(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    old = sqlite3.connect(path)
    old.execute(_V9_FINANCE_TXNS)
    old.execute(
        "INSERT INTO finance_txns (bank, direction, channel, amount_enc, occurred_at, from_sms, "
        "created_at) VALUES ('bob', 'debit', 'upi', x'00', 't', 1, 't')"
    )
    old.execute("PRAGMA user_version=9")
    old.commit()
    old.close()

    db = Database(path)
    columns = {r["name"]: r for r in db.query("PRAGMA table_info(finance_txns)")}
    assert {"from_notification", "inferred", "window_from", "window_to"} <= set(columns)
    assert columns["from_notification"]["notnull"] == 1 and columns["inferred"]["notnull"] == 1
    assert columns["window_from"]["notnull"] == 0 and columns["window_to"]["notnull"] == 0
    row = db.query("SELECT * FROM finance_txns")[0]
    assert (row["from_sms"], row["from_notification"], row["inferred"]) == (1, 0, 0)
    assert (row["window_from"], row["window_to"]) == (None, None)
    assert db.query("PRAGMA user_version")[0][0] == SCHEMA_VERSION == 10
    db.close()
    Database(path).close()  # opening again is a no-op, not a duplicate-column error
