from __future__ import annotations

from datetime import timedelta

from agent.store.db import Database
from agent.store.sync_status import CLASSROOM, SMS_INGEST, last_ok, record_ok
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
