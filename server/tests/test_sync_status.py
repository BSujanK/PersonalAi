from __future__ import annotations

from datetime import timedelta

from agent.store.db import Database
from agent.store.sync_status import (
    CLASSROOM,
    SMS_INGEST,
    last_failure,
    last_ok,
    mail_status_name,
    record_failure,
    record_ok,
)
from tests.support import START, FakeClock


def test_never_recorded_is_none() -> None:
    assert last_ok(Database(":memory:"), SMS_INGEST) is None


def test_record_upserts_and_names_are_independent() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_ok(db, SMS_INGEST, clock)
    clock.advance(timedelta(hours=1))
    record_ok(db, SMS_INGEST, clock)
    assert last_ok(db, SMS_INGEST) == START + timedelta(hours=1)
    assert last_ok(db, CLASSROOM) is None
    assert len(db.query("SELECT * FROM sync_status")) == 1


def test_failure_is_recorded_without_touching_the_ok_time() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_ok(db, CLASSROOM, clock)
    clock.advance(timedelta(hours=1))
    record_failure(db, CLASSROOM, "GoogleNotConfigured for 1 of 1 accounts", clock)
    assert last_ok(db, CLASSROOM) == START
    assert last_failure(db, CLASSROOM) == (
        START + timedelta(hours=1),
        "GoogleNotConfigured for 1 of 1 accounts",
    )
    assert last_failure(db, SMS_INGEST) is None


def test_failure_upserts_and_a_later_ok_clears_it() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_failure(db, SMS_INGEST, "ValueError", clock)
    record_failure(db, SMS_INGEST, "KeyError", clock)
    assert len(db.query("SELECT * FROM sync_failures")) == 1
    assert last_failure(db, SMS_INGEST) == (START, "KeyError")
    record_ok(db, SMS_INGEST, clock)
    assert last_failure(db, SMS_INGEST) is None


def test_ok_clears_only_its_own_failure() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    first, second = mail_status_name("a@example.com"), mail_status_name("b@example.com")
    record_failure(db, first, "ValueError", clock)
    record_failure(db, second, "KeyError", clock)
    record_ok(db, first, clock)
    assert last_failure(db, first) is None
    assert last_failure(db, second) is not None
