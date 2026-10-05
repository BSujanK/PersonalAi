from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from agent.config import Settings
from agent.core.loop import AgentLoop
from agent.core.policy import Decision, evaluate_tool_call
from agent.core.redact import RedactionMap, Redactor
from agent.core.tools import ToolKind
from agent.store.models import ActionStatus
from tests.fakes_workspace import Workspace
from tests.support import DEVICE_ID, request_for
from tests.test_loop import FakeLLM, call, say

ME = "me@example.com"
COLLEGE = "college@example.org"
CREATE: dict[str, Any] = {
    "account": ME,
    "summary": "Study group",
    "start": "2026-10-06T15:00:00+05:30",
    "end": "2026-10-06T16:30:00+05:30",
}


def _create(**changes: Any) -> dict[str, Any]:
    return {**CREATE, **changes}


def _events(w: Workspace, args: dict[str, Any]) -> Any:
    return w.tool("calendar_events").run(args)


def test_tool_kinds() -> None:
    w = Workspace()
    assert w.registry.kind_of("calendar_events") is ToolKind.READ
    assert w.registry.kind_of("calendar_create_event") is ToolKind.WRITE
    assert w.registry.kind_of("calendar_update_event") is ToolKind.WRITE
    assert w.registry.kind_of("calendar_add_deadline") is ToolKind.WRITE


def test_events_merges_accounts_sorted_by_start() -> None:
    w = Workspace()
    w.calendars[ME].add_event(
        id="late", summary="Lunch", start={"dateTime": "2026-10-07T12:00:00+00:00"},
        end={"dateTime": "2026-10-07T13:00:00+00:00"}, location="Cafe",
    )  # fmt: skip
    w.calendars[COLLEGE].add_event(
        id="early", summary="Exam", start={"date": "2026-10-06"}, end={"date": "2026-10-07"}
    )
    found = _events(w, {})
    assert [e["id"] for e in found] == ["early", "late"]
    assert found[0] == {
        "account": COLLEGE, "id": "early", "summary": "Exam", "start": "2026-10-06",
        "end": "2026-10-07", "all_day": True, "location": "",
    }  # fmt: skip
    assert found[1]["all_day"] is False and found[1]["location"] == "Cafe"
    now = w.clock.now
    assert w.calendars[ME].list_calls == [(now, now + timedelta(days=7), None, 20)]


def test_events_single_account_query_and_limit() -> None:
    w = Workspace()
    for i in range(3):
        w.calendars[ME].add_event(summary=f"Talk {i}", start={"date": "2026-10-06"}, end={})
    found = _events(w, {"account": ME, "query": "Talk", "limit": 2, "days": 31})
    assert len(found) == 2
    assert w.calendars[COLLEGE].list_calls == []
    assert w.calendars[ME].list_calls[0][1:] == (w.clock.now + timedelta(days=31), "Talk", 2)


@pytest.mark.parametrize(
    "args",
    [
        {"days": 0}, {"days": 32}, {"days": True}, {"days": "7"}, {"limit": 0}, {"limit": 51},
        {"query": "x" * 101}, {"query": 5}, {"account": "other@example.com"}, {"account": 3},
    ],
)  # fmt: skip
def test_events_validation(args: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _events(Workspace(), args)


@pytest.mark.parametrize(
    "changes",
    [
        {"account": "other@example.com"},
        {"account": None},
        {"summary": ""},
        {"summary": "  "},
        {"summary": "x" * 201},
        {"summary": "line\nbreak"},
        {"summary": 5},
        {"description": "x" * 2001},
        {"description": 5},
        {"location": "x" * 201},
        {"location": "a\nb"},
        {"start": "2026-10-06"},  # mixed date / datetime
        {"start": "2026-10-06T15:00:00", "end": "2026-10-06T16:00:00"},  # naive
        {"start": "2026-10-06T15:00:00+05:30", "end": "2026-10-06T16:00:00"},  # naive end
        {"start": "tomorrow"},
        {"start": None},
        {"end": "2026-10-06T15:00:00+05:30"},  # zero length
        {"end": "2026-10-06T14:00:00+05:30"},  # before start
        {"end": "2026-10-21T15:00:00+05:30"},  # over 14 days
        {"start": "2026-02-30", "end": "2026-03-02"},
        {"start": "2026-10-06", "end": "2026-10-06"},
        {"start": "2026-10-06", "end": "2026-10-21"},
    ],
)
def test_create_validation(changes: dict[str, Any]) -> None:
    w = Workspace()
    with pytest.raises(ValueError):
        w.tool("calendar_create_event").preview(_create(**changes))
    with pytest.raises(ValueError):
        w.tool("calendar_create_event").run(_create(**changes))


def test_create_accepts_dates_and_max_duration() -> None:
    w = Workspace()
    tool = w.tool("calendar_create_event")
    assert tool.preview(_create(start="2026-10-06", end="2026-10-20"))
    assert tool.preview(_create(start="2026-10-06T00:00:00Z", end="2026-10-20T00:00:00Z"))
    with pytest.raises(ValueError):
        tool.preview(_create(start="2026-10-06T00:00:00Z", end="2026-10-20T00:00:01Z"))


def test_create_preview_shows_everything_written() -> None:
    w = Workspace()
    description = "Bring notes.\nLine two: room 4 — bring the lab report too."
    preview = w.tool("calendar_create_event").preview(
        _create(description=description, location="Library")
    )
    lines = preview.splitlines()
    assert lines[0] == f"Create event on {ME}"
    assert "Title: Study group" in lines
    assert "When: 2026-10-06T15:00:00+05:30 → 2026-10-06T16:30:00+05:30" in lines
    assert "Location: Library" in lines
    assert description in preview
    assert lines[-1] == "No guests are invited."


def test_create_body_has_only_allowed_keys() -> None:
    w = Workspace()
    result = w.tool("calendar_create_event").run(
        _create(description="d", location="l", attendees=[{"email": "attacker@example.com"}])
    )
    assert result == {"id": "ev1"}
    assert w.calendars[ME].inserted == [
        {
            "summary": "Study group",
            "start": {"dateTime": "2026-10-06T15:00:00+05:30"},
            "end": {"dateTime": "2026-10-06T16:30:00+05:30"},
            "description": "d",
            "location": "l",
        }
    ]


def test_create_all_day_body_uses_dates() -> None:
    w = Workspace()
    w.tool("calendar_create_event").run(_create(start="2026-10-06", end="2026-10-07"))
    body = w.calendars[ME].inserted[0]
    assert body["start"] == {"date": "2026-10-06"} and body["end"] == {"date": "2026-10-07"}
    assert set(body) == {"summary", "start", "end"}


def test_policy_denies_smuggled_keys() -> None:
    w = Workspace()
    smuggled = _create(attendees=[{"email": "attacker@example.com"}])
    decision, _ = evaluate_tool_call(w.registry, "calendar_create_event", smuggled, 0)
    assert decision is Decision.DENY
    decision, _ = evaluate_tool_call(w.registry, "calendar_create_event", CREATE, 0)
    assert decision is Decision.PROPOSE_WRITE


def test_create_runs_only_after_signed_approval_with_stored_payload() -> None:
    w = Workspace()
    action = w.engine.propose("calendar_create_event", _create(description="d"), None)
    assert w.calendars[ME].inserted == []
    assert "Description:\nd" in action.preview
    w.clock.advance(timedelta(minutes=1))
    done = w.engine.decide(request_for(w.approval_key, action), DEVICE_ID)
    assert done.status is ActionStatus.EXECUTED
    assert len(w.calendars[ME].inserted) == 1
    assert w.calendars[ME].inserted[0]["description"] == "d"
    assert "attendees" not in w.calendars[ME].inserted[0]
    assert w.calendars[COLLEGE].inserted == []


def test_create_not_run_when_rejected() -> None:
    w = Workspace()
    action = w.engine.propose("calendar_create_event", _create(), None)
    w.engine.decide(request_for(w.approval_key, action, "reject"), DEVICE_ID)
    assert w.calendars[ME].inserted == []


def _update(**changes: Any) -> dict[str, Any]:
    return {"account": ME, "event_id": "ev1", **changes}


def _seed(w: Workspace) -> None:
    w.calendars[ME].add_event(
        id="ev1", summary="Old title", location="Old room", description="Old notes",
        start={"dateTime": "2026-10-06T10:00:00+00:00"},
        end={"dateTime": "2026-10-06T11:00:00+00:00"},
    )  # fmt: skip


@pytest.mark.parametrize(
    "args",
    [
        _update(),  # no change
        _update(start="2026-10-06"),  # start without end
        _update(end="2026-10-07"),
        _update(event_id="bad id!"),
        _update(event_id=""),
        _update(event_id="x" * 1025),
        _update(event_id=5),
        _update(account="other@example.com"),
        _update(summary=""),
        _update(summary="a\nb"),
        _update(description="x" * 2001),
        _update(location="x" * 201),
        _update(start="2026-10-06T10:00:00", end="2026-10-06T11:00:00"),
        _update(start="2026-10-06", end="2026-10-06"),
        _update(start="2026-10-06", end="2026-10-30"),
    ],
)
def test_update_validation(args: dict[str, Any]) -> None:
    w = Workspace()
    _seed(w)
    with pytest.raises(ValueError):
        w.tool("calendar_update_event").preview(args)
    with pytest.raises(ValueError):
        w.tool("calendar_update_event").run(args)
    assert w.calendars[ME].patched == []


def test_update_preview_shows_old_and_new_for_changed_fields_only() -> None:
    w = Workspace()
    _seed(w)
    preview = w.tool("calendar_update_event").preview(
        _update(summary="New title", start="2026-10-06", end="2026-10-07", description="New notes")
    )
    lines = preview.splitlines()
    assert lines[0] == f"Change event on {ME}"
    assert "Title: Old title → New title" in lines
    assert (
        "When: 2026-10-06T10:00:00+00:00 → 2026-10-06T11:00:00+00:00 → 2026-10-06 → 2026-10-07"
        in lines
    )
    assert "Description: Old notes → New notes" in lines
    assert not any(line.startswith("Location") for line in lines)


def test_update_preview_survives_unavailable_event() -> None:
    w = Workspace()
    preview = w.tool("calendar_update_event").preview(_update(summary="New title"))
    assert "current details unavailable" in preview
    assert "Title: (unavailable) → New title" in preview
    w.calendars[ME].fail_get = True
    assert "New title" in w.tool("calendar_update_event").preview(_update(summary="New title"))


def test_update_patches_only_given_fields_without_guest_keys() -> None:
    w = Workspace()
    _seed(w)
    args = _update(location="New room", attendees=[{"email": "attacker@example.com"}])
    assert w.tool("calendar_update_event").run(args) == {"id": "ev1"}
    assert w.calendars[ME].patched == [("ev1", {"location": "New room"})]


def test_update_end_to_end_through_approval() -> None:
    w = Workspace()
    _seed(w)
    action = w.engine.propose("calendar_update_event", _update(summary="New title"), None)
    assert w.calendars[ME].patched == []
    w.clock.advance(timedelta(minutes=1))
    assert w.engine.decide(request_for(w.approval_key, action), DEVICE_ID).status is (
        ActionStatus.EXECUTED
    )
    assert w.calendars[ME].patched == [("ev1", {"summary": "New title"})]


def test_update_of_missing_event_fails_the_action() -> None:
    w = Workspace()
    action = w.engine.propose("calendar_update_event", _update(summary="x"), None)
    done = w.engine.decide(request_for(w.approval_key, action), DEVICE_ID)
    assert done.status is ActionStatus.FAILED


def test_model_attempt_with_attendees_stores_nothing() -> None:
    w = Workspace()
    smuggled = _create(attendees=[{"email": "attacker@example.com"}])
    llm = FakeLLM(call("calendar_create_event", smuggled), say("Could not."))
    loop = AgentLoop(llm, w.registry, Redactor([ME]), w.engine, Settings())
    result = loop.run("c1", [], "Add an event", RedactionMap())
    assert result.pending_action_ids == []
    assert w.engine.pending_count() == 0
    assert w.calendars[ME].inserted == []
