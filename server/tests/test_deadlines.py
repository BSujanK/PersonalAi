from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent.core.policy import MAX_PENDING_ACTIONS
from agent.store.models import ActionStatus
from agent.workspace.deadlines import DeadlineProposer, DeadlineScanResult
from tests.fakes_workspace import FakeClassroomApi, Workspace, due_fields
from tests.support import DEVICE_ID, request_for

ME = "me@example.com"
COLLEGE = "college@example.org"
OTHER = "other@example.org"
DUE = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _args(**changes: Any) -> dict[str, Any]:
    base = {
        "calendar_account": ME,
        "classroom_account": COLLEGE,
        "course_id": "c1",
        "coursework_id": "w1",
        "title": "Essay 1",
        "course": "Intro to Examples",
        "due": "2026-10-08T09:30:00+00:00",
    }
    return {**base, **changes}


def _proposer(w: Workspace, accounts: tuple[str, ...] = (COLLEGE,)) -> DeadlineProposer:
    return DeadlineProposer(
        w.db,
        w.engine,
        w.classrooms.__getitem__,
        accounts,
        ME,
        w.clock,
        14,
    )


def _setup(w: Workspace, *, due: datetime | None = DUE, date_only: bool = False) -> None:
    api = w.classrooms[COLLEGE]
    api.courses.clear()
    api.add_course("c1", "Intro to Examples")
    api.coursework = {
        "c1": [{"id": "w1", "title": "Essay 1", **due_fields(due, date_only=date_only)}]
    }


def _rows(w: Workspace) -> list[Any]:
    return w.db.query("SELECT * FROM deadline_proposals")


def _set_status(w: Workspace, action_id: str, status: str) -> None:
    w.db.execute("UPDATE pending_actions SET status = ? WHERE id = ?", (status, action_id))


def _only_action(w: Workspace) -> Any:
    action = w.engine.get(_rows(w)[0]["action_id"])
    assert action is not None
    return action


def test_preview_shows_title_when_account_and_no_guests() -> None:
    w = Workspace()
    lines = w.tool("calendar_add_deadline").preview(_args()).splitlines()
    assert lines[0] == f"Add deadline to the calendar of {ME}"
    assert "Title: Due: Essay 1 (Intro to Examples)" in lines
    assert "When: 2026-10-08T09:00:00+00:00 → 2026-10-08T09:30:00+00:00" in lines
    assert lines[-1] == "No guests are invited."


@pytest.mark.parametrize(
    "changes",
    [
        {"calendar_account": "other@example.com"},
        {"classroom_account": ""},
        {"classroom_account": "a/b@example.org"},
        {"classroom_account": "a b@example.org"},
        {"course_id": "c/1"},
        {"course_id": ""},
        {"coursework_id": "x" * 65},
        {"coursework_id": "w 1"},
        {"title": ""},
        {"title": "x" * 201},
        {"title": "a\nb"},
        {"course": "x" * 201},
        {"course": 5},
        {"due": "2026-10-08T09:30:00"},  # naive
        {"due": "soon"},
        {"due": None},
    ],
)
def test_deadline_validation(changes: dict[str, Any]) -> None:
    w = Workspace()
    with pytest.raises(ValueError):
        w.tool("calendar_add_deadline").preview(_args(**changes))
    with pytest.raises(ValueError):
        w.tool("calendar_add_deadline").run(_args(**changes))
    assert w.calendars[ME].inserted == []


def test_executor_inserts_timed_block_with_marker_and_no_guests() -> None:
    w = Workspace()
    smuggled = _args(attendees=[{"email": "attacker@example.com"}])
    assert w.tool("calendar_add_deadline").run(smuggled) == {"ok": 1, "id": "ev1"}
    assert w.calendars[ME].find_calls == [("personalai_coursework", f"{COLLEGE}/c1/w1")]
    assert w.calendars[ME].inserted == [
        {
            "summary": "Due: Essay 1 (Intro to Examples)",
            "start": {"dateTime": "2026-10-08T09:00:00+00:00"},
            "end": {"dateTime": "2026-10-08T09:30:00+00:00"},
            "description": "Added from Google Classroom.",
            "extendedProperties": {"private": {"personalai_coursework": f"{COLLEGE}/c1/w1"}},
        }
    ]


def test_executor_date_only_due_is_all_day() -> None:
    w = Workspace()
    w.tool("calendar_add_deadline").run(_args(due="2026-10-08"))
    body = w.calendars[ME].inserted[0]
    assert body["start"] == {"date": "2026-10-08"} and body["end"] == {"date": "2026-10-09"}


def test_executor_skips_an_existing_event() -> None:
    w = Workspace()
    tool = w.tool("calendar_add_deadline")
    assert tool.run(_args())["ok"] == 1
    assert tool.run(_args()) == {"ok": 0, "duplicate": True}
    assert len(w.calendars[ME].inserted) == 1
    assert tool.run(_args(coursework_id="w2"))["ok"] == 1
    assert len(w.calendars[ME].inserted) == 2


def test_approval_inserts_exactly_once_with_stored_payload() -> None:
    w = Workspace()
    action = w.engine.propose("calendar_add_deadline", _args(), None)
    assert w.calendars[ME].inserted == []
    w.clock.advance(timedelta(minutes=1))
    done = w.engine.decide(request_for(w.approval_key, action), DEVICE_ID)
    assert done.status is ActionStatus.EXECUTED
    assert len(w.calendars[ME].inserted) == 1
    assert "attendees" not in w.calendars[ME].inserted[0]


def test_proposes_once_and_records_the_row() -> None:
    w = Workspace()
    _setup(w)
    proposer = _proposer(w)
    assert proposer.run().proposed == 1
    row = _rows(w)[0]
    assert (row["classroom_account"], row["course_id"], row["coursework_id"]) == (
        COLLEGE,
        "c1",
        "w1",
    )
    assert row["due_at"] == DUE.isoformat()
    action = _only_action(w)
    assert action.tool_name == "calendar_add_deadline"
    assert action.payload == _args()
    assert action.status is ActionStatus.PENDING
    assert w.calendars[ME].inserted == []
    assert proposer.run().proposed == 0
    assert w.engine.pending_count() == 1


def test_no_calendar_account_proposes_nothing() -> None:
    w = Workspace()
    _setup(w)
    proposer = DeadlineProposer(
        w.db, w.engine, w.classrooms.__getitem__, (COLLEGE,), None, w.clock, 14
    )
    assert proposer.run().proposed == 0
    assert w.engine.pending_count() == 0


def test_skips_past_out_of_horizon_and_undated_items() -> None:
    w = Workspace()
    now = w.clock.now
    api = w.classrooms[COLLEGE]
    api.add_course("c1", "Intro to Examples")
    api.coursework = {
        "c1": [
            {"id": "past", "title": "P", **due_fields(now - timedelta(minutes=1))},
            {"id": "far", "title": "F", **due_fields(now + timedelta(days=14, minutes=1))},
            {"id": "none", "title": "N"},
            {"id": "bad", "title": "B", "dueDate": {"year": 2026}},
            {"id": "ok", "title": "OK", **due_fields(now + timedelta(days=14))},
        ]
    }
    assert _proposer(w).run().proposed == 1
    assert _rows(w)[0]["coursework_id"] == "ok"


def test_date_only_due_today_is_still_proposed() -> None:
    w = Workspace()
    _setup(w, due=w.clock.now, date_only=True)
    assert _proposer(w).run().proposed == 1
    assert _only_action(w).payload["due"] == "2026-10-05"


@pytest.mark.parametrize("status", ["approved", "executed", "rejected"])
def test_never_reproposes_decided_actions_even_after_a_day(status: str) -> None:
    w = Workspace()
    _setup(w, due=w.clock.now + timedelta(days=13))
    proposer = _proposer(w)
    assert proposer.run().proposed == 1
    _set_status(w, _rows(w)[0]["action_id"], status)
    w.clock.advance(timedelta(days=3))
    assert proposer.run().proposed == 0


def test_does_not_repropose_while_pending() -> None:
    w = Workspace()
    _setup(w, due=w.clock.now + timedelta(days=13))
    proposer = _proposer(w)
    assert proposer.run().proposed == 1
    w.clock.advance(timedelta(minutes=10))
    assert proposer.run().proposed == 0


@pytest.mark.parametrize("status", ["expired", "failed"])
def test_reproposes_expired_or_failed_only_after_24_hours(status: str) -> None:
    w = Workspace()
    _setup(w, due=w.clock.now + timedelta(days=13))
    proposer = _proposer(w)
    assert proposer.run().proposed == 1
    first = _rows(w)[0]["action_id"]
    _set_status(w, first, status)
    w.clock.advance(timedelta(hours=23, minutes=59))
    assert proposer.run().proposed == 0
    w.clock.advance(timedelta(minutes=2))
    assert proposer.run().proposed == 1
    assert _rows(w)[0]["action_id"] != first
    assert len(_rows(w)) == 1


def test_pending_action_that_lapses_is_reproposed_after_24_hours() -> None:
    w = Workspace()
    _setup(w, due=w.clock.now + timedelta(days=13))
    proposer = _proposer(w)
    assert proposer.run().proposed == 1
    w.clock.advance(timedelta(hours=1))
    assert proposer.run().proposed == 0  # now expired, but not yet 24 hours old
    assert _only_action(w).status is ActionStatus.EXPIRED
    w.clock.advance(timedelta(hours=24))
    assert proposer.run().proposed == 1


def test_reproposes_when_the_due_date_moves_even_after_rejection() -> None:
    w = Workspace()
    _setup(w)
    proposer = _proposer(w)
    assert proposer.run().proposed == 1
    _set_status(w, _rows(w)[0]["action_id"], "rejected")
    assert proposer.run().proposed == 0
    _setup(w, due=DUE + timedelta(days=1))
    assert proposer.run().proposed == 1
    assert _rows(w)[0]["due_at"] == (DUE + timedelta(days=1)).isoformat()
    assert _only_action(w).payload["due"] == "2026-10-09T09:30:00+00:00"


def test_stops_at_half_the_pending_cap() -> None:
    w = Workspace()
    now = w.clock.now
    api = w.classrooms[COLLEGE]
    api.add_course("c1", "Intro to Examples")
    api.coursework = {
        "c1": [
            {"id": f"w{i}", "title": f"T{i}", **due_fields(now + timedelta(days=1, minutes=i))}
            for i in range(MAX_PENDING_ACTIONS)
        ]
    }
    half = MAX_PENDING_ACTIONS // 2
    for i in range(3):
        w.engine.propose("calendar_add_deadline", _args(coursework_id=f"old{i}"), None)
    proposer = _proposer(w)
    assert proposer.run().proposed == half - 3
    assert w.engine.pending_count() == half
    assert proposer.run().proposed == 0


def test_cap_already_reached_proposes_nothing() -> None:
    w = Workspace()
    _setup(w)
    for i in range(MAX_PENDING_ACTIONS // 2):
        w.engine.propose("calendar_add_deadline", _args(coursework_id=f"old{i}"), None)
    assert _proposer(w).run().proposed == 0
    assert _rows(w) == []


def test_one_failing_account_does_not_stop_the_others(caplog: pytest.LogCaptureFixture) -> None:
    w = Workspace()
    w.classrooms[OTHER] = FakeClassroomApi()
    w.classrooms[OTHER].fail = RuntimeError("secret title Essay for other@example.org")
    _setup(w)
    with caplog.at_level(logging.INFO, logger="agent.workspace.deadlines"):
        assert _proposer(w, (OTHER, COLLEGE)).run().proposed == 1
    text = caplog.text
    assert "deadline scan failed for an account: RuntimeError" in text
    for private in ("secret", "Essay", "example.org", "Intro"):
        assert private not in text
    assert "proposed 1 actions" in text


def test_result_reports_scanned_and_failed_accounts() -> None:
    w = Workspace()
    w.classrooms[OTHER] = FakeClassroomApi()
    w.classrooms[OTHER].fail = RuntimeError("private text")
    _setup(w)
    result = _proposer(w, (OTHER, COLLEGE)).run()
    assert result == DeadlineScanResult(1, 1, {OTHER: "RuntimeError"})


def test_result_when_every_account_fails() -> None:
    w = Workspace()
    w.classrooms[OTHER] = FakeClassroomApi()
    for account in (COLLEGE, OTHER):
        w.classrooms[account].fail = KeyError("private text")
    result = _proposer(w, (OTHER, COLLEGE)).run()
    assert result == DeadlineScanResult(0, 0, {OTHER: "KeyError", COLLEGE: "KeyError"})


def test_full_queue_is_neither_scanned_nor_failed() -> None:
    w = Workspace()
    _setup(w)
    for i in range(MAX_PENDING_ACTIONS // 2):
        w.engine.propose("calendar_add_deadline", _args(coursework_id=f"f{i}"), None)
    assert _proposer(w).run() == DeadlineScanResult(0, 0, {})


def test_hostile_titles_are_flattened_and_bad_ids_skipped() -> None:
    w = Workspace()
    api = w.classrooms[COLLEGE]
    api.add_course("c1", "Intro\nto   Examples")
    api.coursework = {
        "c1": [
            {"id": "w1", "title": "Line one\nLine two " + "x" * 300, **due_fields(DUE)},
            {"id": "bad id", "title": "Skipped", **due_fields(DUE)},
            {"title": "No id", **due_fields(DUE)},
        ]
    }
    assert _proposer(w).run().proposed == 1
    payload = _only_action(w).payload
    assert payload["course"] == "Intro to Examples"
    assert payload["title"].startswith("Line one Line two ") and len(payload["title"]) == 200
