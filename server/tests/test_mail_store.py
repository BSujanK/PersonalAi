from __future__ import annotations

from pathlib import Path

import pytest

from agent.connectors.gmail import MailMessage
from agent.mail.store import MailStore
from agent.store.crypto import DecryptionError, FieldCipher
from agent.store.db import Database
from tests.support import FakeClock

KEY = bytes(range(32))


def _msg(message_id: str = "m1", **kw: object) -> MailMessage:
    base: dict[str, object] = {
        "account": "me@example.com",
        "id": message_id,
        "thread_id": "t1",
        "history_id": "10",
        "internal_date": 1_000,
        "from_addr": "alice@example.com",
        "from_name": "Alice Example",
        "to": ("me@example.com",),
        "subject": "Quarterly plan",
        "snippet": "snip",
        "body": "body text",
        "label_ids": ("INBOX",),
        "list_unsubscribe": False,
    }
    base.update(kw)
    return MailMessage(**base)  # type: ignore[arg-type]


def _store(db: Database | None = None) -> MailStore:
    return MailStore(db or Database(":memory:"), FieldCipher(KEY), KEY, FakeClock())


def test_upsert_roundtrip_and_new_flag() -> None:
    store = _store()
    assert store.upsert(_msg()) is True
    got = store.get("me@example.com", "m1")
    assert got is not None
    assert (got.from_addr, got.from_name, got.subject, got.body) == (
        "alice@example.com",
        "Alice Example",
        "Quarterly plan",
        "body text",
    )
    assert got.to == ("me@example.com",)
    assert got.label_ids == ("INBOX",)
    assert got.category is None
    assert store.upsert(_msg(subject="Edited")) is False
    updated = store.get("me@example.com", "m1")
    assert updated is not None
    assert updated.subject == "Edited"
    assert store.get("me@example.com", "nope") is None


def test_upsert_keeps_category() -> None:
    store = _store()
    store.upsert(_msg())
    store.set_category("me@example.com", "m1", "promo", "rule", "keyword", "because")
    store.upsert(_msg(subject="again"))
    got = store.get("me@example.com", "m1")
    assert got is not None
    assert (got.category, got.category_source, got.reason, got.reason_text) == (
        "promo",
        "rule",
        "keyword",
        "because",
    )


def test_labels_deleted_and_recent() -> None:
    store = _store()
    for i, ts in enumerate((1_000, 3_000, 2_000)):
        store.upsert(_msg(f"m{i}", internal_date=ts))
    store.upsert(_msg("x", account="other@example.com", internal_date=5_000))
    store.set_category("me@example.com", "m1", "important", "rule", "vip")
    assert [m.id for m in store.recent(0, account="me@example.com", limit=10)] == ["m1", "m2", "m0"]
    assert [m.id for m in store.recent(2_000, account="me@example.com", limit=10)] == ["m1", "m2"]
    assert [m.id for m in store.recent(0, category="important", limit=10)] == ["m1"]
    assert len(store.recent(0, limit=2)) == 2
    assert store.update_labels("me@example.com", "m0", ["STARRED"]) is True
    assert store.get_labels("me@example.com", "m0") == ("STARRED",)
    assert store.update_labels("me@example.com", "zz", []) is False
    assert store.mark_deleted("me@example.com", "m1") is True
    assert "m1" not in [m.id for m in store.recent(0, account="me@example.com", limit=10)]
    assert store.mark_deleted("me@example.com", "zz") is False


def test_replied_and_sender_rules_are_case_insensitive() -> None:
    store = _store()
    store.add_replied("me@example.com", ["Bob@Example.com"])
    assert store.has_replied("me@example.com", "bob@example.com")
    assert not store.has_replied("other@example.com", "bob@example.com")
    assert store.sender_rule("a@example.com") is None
    store.set_sender_rule("A@Example.com", "spam", "feedback")
    store.set_sender_rule("a@example.com", "promo", "feedback")
    assert store.sender_rule("a@EXAMPLE.com") == "promo"


def test_addr_hash_is_keyed() -> None:
    a = _store().addr_hash(" Bob@Example.com ")
    assert a == _store().addr_hash("bob@example.com")
    other = MailStore(Database(":memory:"), FieldCipher(KEY), bytes(32), FakeClock())
    assert other.addr_hash("bob@example.com") != a
    assert "bob" not in a


def test_feedback_and_history_cursor() -> None:
    store = _store()
    store.upsert(_msg("m1"))
    store.upsert(_msg("m2"))
    store.record_feedback("me@example.com", "m1", None, "important")
    store.record_feedback("me@example.com", "m2", "normal", "spam")
    store.record_feedback("me@example.com", "gone", None, "spam")
    items = store.recent_feedback(5)
    assert [(i.mail.id, i.new_category) for i in items] == [("m2", "spam"), ("m1", "important")]
    assert store.get_history_id("me@example.com") is None
    store.set_history_id("me@example.com", "5", "t")
    store.set_history_id("me@example.com", "9", "t2")
    assert store.get_history_id("me@example.com") == "9"


def test_ciphertext_is_bound_to_its_row(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    store = _store(db)
    store.upsert(_msg("m1"))
    store.upsert(_msg("m2"))
    blob = db.query("SELECT subject_enc FROM mail_messages WHERE id = 'm1'")[0][0]
    db.execute("UPDATE mail_messages SET subject_enc = ? WHERE id = 'm2'", (blob,))
    with pytest.raises(DecryptionError):
        store.get("me@example.com", "m2")


def test_schema_v1_database_upgrades(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    Database(path).close()
    db = Database(path)
    tables = {r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "mail_messages",
        "mail_accounts",
        "mail_replied",
        "sender_rules",
        "mail_feedback",
    } <= tables
