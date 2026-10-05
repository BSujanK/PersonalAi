from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent.connectors.gmail import GmailApi, MailMessage
from agent.mail.store import MailStore
from agent.mail.sync import MailSync
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from tests.fakes_gmail import FakeGmailApi
from tests.support import FakeClock

KEY = bytes(range(32))
ACCOUNT = "me@example.com"
SECRET_SUBJECT = "Zebra-Quartz subject"
SECRET_BODY = "Marmalade-Nebula body text"
SECRET_FROM = "pelican.sender@example.org"
SECRET_NAME = "Pelican Sender"


class Recorder:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def classify(self, msg: MailMessage) -> object:
        self.seen.append(msg.id)
        return None


def _setup(
    path: Path | str = ":memory:", page_size: int = 2, classifier: Recorder | None = None
) -> tuple[MailSync, MailStore, FakeGmailApi, Database]:
    db = Database(path)
    clock = FakeClock()
    store = MailStore(db, FieldCipher(KEY), KEY, clock)
    api = FakeGmailApi(ACCOUNT, page_size=page_size)

    def api_for(account: str) -> GmailApi:
        assert account == ACCOUNT
        return api

    return MailSync(store, api_for, classifier, clock, 7), store, api, db


def test_full_sync_pages_stores_and_records_cursor() -> None:
    rec = Recorder()
    sync, store, api, _ = _setup(classifier=rec)
    for i in range(5):
        api.add_message(f"m{i}", internal_date=1_000 + i)
    cursor = api.profile()["historyId"]
    stats = sync.sync_account(ACCOUNT)
    assert (stats.added, stats.updated, stats.deleted, stats.full) == (5, 0, 0, True)
    assert store.get_history_id(ACCOUNT) == cursor
    assert api.list_queries[0] == "newer_than:7d"
    assert len(api.list_queries) == 3  # 5 ids, 2 per page
    assert sorted(rec.seen) == [f"m{i}" for i in range(5)]


def test_full_sync_reads_cursor_before_listing() -> None:
    sync, store, api, _ = _setup()
    api.add_message("m0")
    original = api.list_message_ids

    def listing(query: str, token: str | None) -> tuple[list[str], str | None]:
        api.add_message("late")  # arrives while listing
        return original(query, token)

    api.list_message_ids = listing  # type: ignore[method-assign]
    before = api.profile()["historyId"]
    sync.sync_account(ACCOUNT)
    assert store.get_history_id(ACCOUNT) == before
    api.list_message_ids = original  # type: ignore[method-assign]
    stats = sync.sync_account(ACCOUNT)
    assert stats.full is False
    assert store.get(ACCOUNT, "late") is not None


def test_full_sync_caps_ids() -> None:
    sync, _store, api, _ = _setup(page_size=500)
    for i in range(2100):
        api.add_message(f"m{i:05d}")
    stats = sync.sync_account(ACCOUNT)
    assert stats.added == 2000


def test_incremental_add_labels_delete_and_idempotence() -> None:
    rec = Recorder()
    sync, store, api, _ = _setup(classifier=rec)
    api.add_message("m1")
    api.add_message("m2")
    api.add_message("m3")
    sync.sync_account(ACCOUNT)
    rec.seen.clear()

    api.add_message("m4")
    api.add_message("m5")
    api.remove_label("m1", "UNREAD")
    api.add_label("m2", "STARRED")
    api.delete_message("m3")
    stats = sync.sync_account(ACCOUNT)
    assert (stats.added, stats.updated, stats.deleted, stats.full) == (2, 2, 1, False)
    assert rec.seen == ["m4", "m5"]
    m1 = store.get(ACCOUNT, "m1")
    m2 = store.get(ACCOUNT, "m2")
    assert m1 is not None and m1.label_ids == ("INBOX",)
    assert m2 is not None and m2.label_ids == ("INBOX", "UNREAD", "STARRED")
    assert [m.id for m in store.recent(0, account=ACCOUNT, limit=10)].count("m3") == 0

    fetched = len(api.get_calls)
    again = sync.sync_account(ACCOUNT)
    assert (again.added, again.updated, again.deleted) == (0, 0, 0)
    assert len(api.get_calls) == fetched


def test_delta_labels_applied_when_record_lacks_label_ids() -> None:
    sync, store, api, _ = _setup()
    api.add_message("m1")
    sync.sync_account(ACCOUNT)
    api.add_label("m1", "STARRED")
    api.remove_label("m1", "INBOX")
    for record in api.history:
        for key in ("labelsAdded", "labelsRemoved"):
            for entry in record.get(key, []):
                del entry["message"]["labelIds"]
    sync.sync_account(ACCOUNT)
    assert store.get_labels(ACCOUNT, "m1") == ("UNREAD", "STARRED")


def test_added_then_deleted_message_is_skipped() -> None:
    sync, store, api, _ = _setup()
    api.add_message("m0")
    sync.sync_account(ACCOUNT)
    api.add_message("gone")
    api.delete_message("gone")
    stats = sync.sync_account(ACCOUNT)
    assert (stats.added, stats.deleted) == (0, 0)
    assert store.get(ACCOUNT, "gone") is None


def test_history_expired_triggers_full_sync() -> None:
    sync, store, api, _ = _setup()
    api.add_message("m1")
    sync.sync_account(ACCOUNT)
    api.add_message("m2")
    api.expire_history()
    stats = sync.sync_account(ACCOUNT)
    assert stats.full is True
    assert (stats.added, stats.updated) == (1, 1)
    assert store.get_history_id(ACCOUNT) == api.profile()["historyId"]


def test_failure_mid_history_does_not_advance_cursor() -> None:
    sync, store, api, _ = _setup()
    api.add_message("m1")
    sync.sync_account(ACCOUNT)
    cursor = store.get_history_id(ACCOUNT)
    api.add_message("m2")
    original = api.get_message

    def boom(message_id: str) -> dict[str, object]:
        raise RuntimeError("network")

    api.get_message = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        sync.sync_account(ACCOUNT)
    assert store.get_history_id(ACCOUNT) == cursor
    api.get_message = original  # type: ignore[method-assign]
    assert sync.sync_account(ACCOUNT).added == 1


def test_sent_mail_records_replied_recipients() -> None:
    sync, store, api, _ = _setup()
    api.add_message("s1", labels=("SENT",), from_=ACCOUNT, to="Bob <bob@example.com>")
    api.add_message("i1", to="other@example.com")
    sync.sync_account(ACCOUNT)
    assert store.has_replied(ACCOUNT, "bob@example.com")
    assert not store.has_replied(ACCOUNT, "other@example.com")


def test_malformed_and_vanished_messages_are_skipped() -> None:
    sync, store, api, _ = _setup()
    api.add_message("ok")
    api.add_message("bad")
    del api.messages["bad"]["payload"]
    api.add_message("vanish")
    original = api.list_message_ids

    def listing(query: str, token: str | None) -> tuple[list[str], str | None]:
        ids, nxt = original(query, token)
        return [*ids, "vanish"], nxt

    del api.messages["vanish"]
    api.list_message_ids = listing  # type: ignore[method-assign]
    stats = sync.sync_account(ACCOUNT)
    assert stats.added == 1
    assert store.get(ACCOUNT, "ok") is not None


class _BrokenClassifier:
    def classify(self, msg: MailMessage) -> object:
        raise RuntimeError("model down")


def test_classifier_failure_does_not_fail_sync() -> None:
    sync, _store, api, _ = _setup()
    sync._classifier = _BrokenClassifier()
    api.add_message("m1")
    assert sync.sync_account(ACCOUNT).added == 1


def test_sync_all_isolates_failures() -> None:
    sync, _store, api, _ = _setup()
    api.add_message("m1")

    def api_for(account: str) -> GmailApi:
        if account == "bad@example.com":
            raise RuntimeError("no token")
        return api

    sync._api_for = api_for
    results = sync.sync_all(["bad@example.com", ACCOUNT])
    assert results["bad@example.com"] == "RuntimeError"
    assert getattr(results[ACCOUNT], "added", None) == 1


def _secret_mail(api: FakeGmailApi) -> None:
    api.add_message(
        "s1",
        from_=f"{SECRET_NAME} <{SECRET_FROM}>",
        subject=SECRET_SUBJECT,
        body=SECRET_BODY,
    )


def test_database_file_holds_no_plaintext_mail(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    sync, store, api, db = _setup(path)
    _secret_mail(api)
    sync.sync_account(ACCOUNT)
    got = store.get(ACCOUNT, "s1")
    assert got is not None and got.subject == SECRET_SUBJECT
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw = b"".join(p.read_bytes() for p in tmp_path.iterdir() if p.name.startswith("agent.db"))
    assert len(raw) > 0
    for secret in (SECRET_SUBJECT, SECRET_BODY, SECRET_FROM, SECRET_NAME, "Zebra", "Marmalade"):
        assert secret.encode() not in raw
    assert store.addr_hash(SECRET_FROM).encode() in raw  # only the keyed hash is indexed


def test_sync_logs_contain_no_mail_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sync, _store, api, _ = _setup()
    _secret_mail(api)
    api.add_message("bad")
    del api.messages["bad"]["payload"]
    sync.sync_account(ACCOUNT)
    api.add_message("s2", subject=SECRET_SUBJECT, body=SECRET_BODY, from_=SECRET_FROM)
    api.expire_history()
    sync.sync_account(ACCOUNT)
    sync._api_for = lambda a: (_ for _ in ()).throw(RuntimeError(SECRET_SUBJECT))
    sync.sync_all([ACCOUNT])
    assert caplog.records
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (SECRET_SUBJECT, SECRET_BODY, SECRET_FROM, SECRET_NAME, ACCOUNT, "example."):
        assert secret not in text
