from __future__ import annotations

from datetime import timedelta

from agent.store.db import Database
from agent.store.sync_status import (
    CLASSROOM,
    MAIL,
    SMS_INGEST,
    last_failure,
    last_ok,
    record_failure,
    record_ok,
    record_scan,
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


def test_record_scan_needs_one_good_account_to_be_ok() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_scan(db, CLASSROOM, clock, succeeded=0, failures=["GoogleNotConfigured"] * 2)
    assert last_ok(db, CLASSROOM) is None
    failure = last_failure(db, CLASSROOM)
    assert failure is not None and not failure.partial
    assert failure.reason == "2 of 2 account(s) failed: GoogleNotConfigured"


def test_record_scan_partial_failure_is_ok_but_remembered() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_scan(db, MAIL, clock, succeeded=1, failures=["HttpError"])
    assert last_ok(db, MAIL) == START
    failure = last_failure(db, MAIL)
    assert failure is not None and failure.partial
    assert failure.reason == "1 of 2 account(s) failed: HttpError"


def test_a_fully_good_run_clears_the_failure() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_scan(db, MAIL, clock, succeeded=0, failures=["HttpError"])
    clock.advance(timedelta(minutes=5))
    record_scan(db, MAIL, clock, succeeded=2, failures=[])
    assert last_failure(db, MAIL) is None
    assert last_ok(db, MAIL) == START + timedelta(minutes=5)


def test_a_failure_after_ok_keeps_the_old_ok_time() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    record_ok(db, CLASSROOM, clock)
    clock.advance(timedelta(hours=2))
    record_failure(db, CLASSROOM, clock, "boom")
    assert last_ok(db, CLASSROOM) == START
    failure = last_failure(db, CLASSROOM)
    assert failure is not None and failure.at == START + timedelta(hours=2)


def test_failure_reason_is_flattened_and_capped() -> None:
    db = Database(":memory:")
    record_failure(db, SMS_INGEST, FakeClock(), "line one\nline two <b>" + "x" * 500)
    failure = last_failure(db, SMS_INGEST)
    assert failure is not None
    assert "\n" not in failure.reason and "<" not in failure.reason
    assert len(failure.reason) == 200
