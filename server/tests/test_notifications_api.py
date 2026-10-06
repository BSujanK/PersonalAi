from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.connectors.gcal import NotOwnEvent
from agent.store.keystore import KeyStore
from tests.proactive_support import ME, ProEnv, mail_message, make_env
from tests.support import make_registry
from tests.test_api import _auth
from tests.test_loop import FakeLLM, say

IST = timezone(timedelta(minutes=330))


@dataclass
class NotifyApi:
    env: ProEnv
    client: TestClient
    headers: dict[str, str]
    device_id: str


def _api(**settings: Any) -> NotifyApi:
    env = make_env(**settings)
    keystore = KeyStore()
    app = create_app(
        env.settings,
        db=env.db,
        keystore=keystore,
        llm=FakeLLM(say("hi")),
        registry=make_registry([]),
        clock=env.clock,
        proactive=env.services,
    )
    client = TestClient(app)
    code = open_pairing_window(env.db, env.clock, 300)
    paired = client.post("/pair", json={"code": code, "device_name": "Pixel"}).json()
    return NotifyApi(env, client, _auth(paired), paired["device_id"])


def _add_deadline(api: NotifyApi, key: str, due: date | datetime, title: str = "Fee") -> None:
    api.env.services.deadlines.store.insert(
        source="mail",
        source_key=key,
        source_account=ME,
        source_id=key,
        kind="fee",
        title=title,
        due=due,
        found_by="rule",
    )


def _get(api: NotifyApi, path: str) -> Any:
    response = api.client.get(path, headers=api.headers)
    assert response.status_code == 200, response.text
    return response.json()


# --- GET /notifications ------------------------------------------------------------------------


def test_feed_is_ascending_and_filtered_by_after_and_limit() -> None:
    api = _api()
    alerts = api.env.services.alerts
    for i in range(4):
        alerts.add("briefing", f"k{i}", f"T{i}", f"B{i}", {"type": "today"})
    alerts.add(
        "calendar_added",
        "undo-me",
        "Added",
        "Fee",
        {"type": "deadline", "deadline_id": 7},
        ("undo",),
    )
    body = _get(api, "/notifications")
    assert [i["id"] for i in body["items"]] == [1, 2, 3, 4, 5] and body["latest_id"] == 5
    first = body["items"][0]
    assert first == {
        "id": 1,
        "kind": "briefing",
        "title": "T0",
        "body": "B0",
        "created_at": api.env.clock.now.isoformat(),
        "target": {"type": "today"},
    }
    assert "actions" not in first
    assert body["items"][4]["actions"] == ["undo"]
    assert body["items"][4]["target"] == {"type": "deadline", "deadline_id": 7}
    assert [i["id"] for i in _get(api, "/notifications?after=3")["items"]] == [4, 5]
    limited = _get(api, "/notifications?after=1&limit=2")
    assert [i["id"] for i in limited["items"]] == [2, 3] and limited["latest_id"] == 5
    assert _get(api, "/notifications?after=5") == {"items": [], "latest_id": 5}


def test_empty_feed_has_latest_id_zero() -> None:
    assert _get(_api(), "/notifications") == {"items": [], "latest_id": 0}


@pytest.mark.parametrize("query", ["after=-1", "after=x", "limit=0", "limit=101", "limit=x"])
def test_feed_validates_parameters(query: str) -> None:
    api = _api()
    assert api.client.get(f"/notifications?{query}", headers=api.headers).status_code == 422


def test_feed_carries_alerts_raised_by_the_job() -> None:
    api = _api()
    api.env.deliver(mail_message("a", subject="Tuition fee"), "important")
    api.env.clock.advance(timedelta(days=1))
    api.env.services.alert_job.run()
    kinds = [i["kind"] for i in _get(api, "/notifications")["items"]]
    assert "calendar_added" in kinds


# --- settings ----------------------------------------------------------------------------------


def test_settings_default_and_round_trip_with_audit() -> None:
    api = _api(briefing_time="06:15")
    assert _get(api, "/notifications/settings") == {
        "important_mail": True,
        "deadlines": True,
        "briefing": True,
        "briefing_time": "06:15",
    }
    new = {"important_mail": False, "deadlines": True, "briefing": False, "briefing_time": "21:05"}
    response = api.client.put("/notifications/settings", json=new, headers=api.headers)
    assert (response.status_code, response.json()) == (200, new)
    assert _get(api, "/notifications/settings") == new
    [row] = api.env.db.query("SELECT * FROM audit_log WHERE event = 'alert_settings'")
    assert (row["actor"], row["detail"]) == (f"device:{api.device_id}", "")


GOOD = {"important_mail": True, "deadlines": True, "briefing": True, "briefing_time": "07:30"}


@pytest.mark.parametrize(
    "bad",
    [
        {k: v for k, v in GOOD.items() if k != "briefing"},
        {k: v for k, v in GOOD.items() if k != "briefing_time"},
        {**GOOD, "briefing_time": "24:00"},
        {**GOOD, "briefing_time": "7:30"},
        {**GOOD, "briefing_time": "07:60"},
        {**GOOD, "briefing_time": "07:30:00"},
        {**GOOD, "briefing_time": "07:30\n"},
        {**GOOD, "briefing_time": 730},
        {**GOOD, "important_mail": "yes"},
        {**GOOD, "deadlines": 1},
        {**GOOD, "briefing": None},
        {**GOOD, "extra": True},
    ],
)
def test_settings_validation(bad: dict[str, Any]) -> None:
    api = _api()
    assert (
        api.client.put("/notifications/settings", json=bad, headers=api.headers).status_code == 422
    )
    assert _get(api, "/notifications/settings") == GOOD
    assert api.env.db.query("SELECT * FROM audit_log WHERE event = 'alert_settings'") == []


@pytest.mark.parametrize("time", ["00:00", "09:59", "19:00", "23:59"])
def test_settings_accept_every_valid_time_shape(time: str) -> None:
    api = _api()
    response = api.client.put(
        "/notifications/settings", json={**GOOD, "briefing_time": time}, headers=api.headers
    )
    assert response.status_code == 200 and response.json()["briefing_time"] == time


# --- GET /deadlines ----------------------------------------------------------------------------


def test_deadlines_listing_shape_order_and_window() -> None:
    api = _api()
    _add_deadline(api, "later", date(2026, 10, 15), "Later")
    _add_deadline(api, "soon", datetime(2026, 10, 6, 17, 0, tzinfo=IST), "Soon")
    _add_deadline(api, "far", date(2026, 11, 30), "Far")
    _add_deadline(api, "past", date(2026, 10, 1), "Past")
    items = _get(api, "/deadlines")["items"]
    assert [i["title"] for i in items] == ["Soon", "Later"]
    assert items[0] == {
        "id": 2,
        "kind": "fee",
        "title": "Soon",
        "due": "2026-10-06T17:00:00+05:30",
        "source": "mail",
        "source_account": ME,
        "source_id": "soon",
        "calendar_added": False,
        "status": "active",
    }
    assert items[1]["due"] == "2026-10-15"
    assert [i["title"] for i in _get(api, "/deadlines?days=2")["items"]] == ["Soon"]
    assert [i["title"] for i in _get(api, "/deadlines?days=60")["items"]] == [
        "Soon",
        "Later",
        "Far",
    ]


@pytest.mark.parametrize("query", ["days=0", "days=61", "days=x"])
def test_deadlines_validate_days(query: str) -> None:
    api = _api()
    assert api.client.get(f"/deadlines?{query}", headers=api.headers).status_code == 422


def test_deadlines_show_calendar_added_and_undone() -> None:
    api = _api()
    _add_deadline(api, "a", date(2026, 10, 10), "On calendar")
    assert api.env.services.autocal.run() == 1
    _add_deadline(api, "b", date(2026, 10, 11), "Not yet")
    items = {i["title"]: i for i in _get(api, "/deadlines")["items"]}
    assert items["On calendar"]["calendar_added"] and not items["Not yet"]["calendar_added"]
    assert api.client.post("/deadlines/1/undo", headers=api.headers).status_code == 200
    undone = {i["title"]: i for i in _get(api, "/deadlines")["items"]}["On calendar"]
    assert (undone["calendar_added"], undone["status"]) == (False, "undone")


# --- POST /deadlines/{id}/undo -----------------------------------------------------------------


def _with_auto_event(api: NotifyApi) -> None:
    _add_deadline(api, "a", date(2026, 10, 10))
    assert api.env.services.autocal.run() == 1


def test_undo_removes_the_event_and_audits_the_device() -> None:
    api = _api()
    _with_auto_event(api)
    response = api.client.post("/deadlines/1/undo", headers=api.headers)
    assert (response.status_code, response.json()) == (200, {"status": "undone"})
    assert api.env.calendar.deleted == ["auto1"]
    [row] = api.env.db.query("SELECT * FROM audit_log WHERE event = 'calendar_auto_undo'")
    assert (row["actor"], row["detail"]) == (f"device:{api.device_id}", "deadline:1")


def test_undo_unknown_or_repeated_is_404() -> None:
    api = _api()
    _with_auto_event(api)
    _add_deadline(api, "no-event", date(2026, 10, 11))
    api.env.calendar.events["foreign"] = {"id": "foreign"}
    for path in ("/deadlines/99/undo", "/deadlines/2/undo"):
        response = api.client.post(path, headers=api.headers)
        assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert api.client.post("/deadlines/1/undo", headers=api.headers).status_code == 200
    assert api.client.post("/deadlines/1/undo", headers=api.headers).status_code == 404
    assert api.env.calendar.deleted == ["auto1"] and "foreign" in api.env.calendar.events


def test_undo_refused_is_409_and_changes_nothing() -> None:
    api = _api()
    _with_auto_event(api)

    def refuse(event_id: str, marker: str) -> None:
        raise NotOwnEvent(event_id)

    api.env.calendar.delete_own = refuse  # type: ignore[method-assign]
    response = api.client.post("/deadlines/1/undo", headers=api.headers)
    assert (response.status_code, response.json()) == (409, {"detail": "refused"})
    assert api.env.db.query("SELECT undone_at FROM auto_events")[0]["undone_at"] is None


@pytest.mark.parametrize("path", ["/deadlines/0/undo", "/deadlines/-1/undo", "/deadlines/x/undo"])
def test_undo_validates_the_id(path: str) -> None:
    api = _api()
    assert api.client.post(path, headers=api.headers).status_code == 422


# --- auth and wiring ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/notifications"),
        ("GET", "/notifications/settings"),
        ("PUT", "/notifications/settings"),
        ("GET", "/deadlines"),
        ("POST", "/deadlines/1/undo"),
    ],
)
def test_every_route_needs_the_device_token(method: str, path: str) -> None:
    api = _api()
    for headers in ({}, {"Authorization": "Bearer nope"}):
        response = api.client.request(method, path, headers=headers, json=GOOD)
        assert response.status_code in (401, 403)


def test_routes_are_absent_without_proactive_services() -> None:
    env = make_env()
    app = create_app(
        Settings(),
        db=env.db,
        keystore=KeyStore(),
        llm=FakeLLM(say("hi")),
        registry=make_registry([]),
        clock=env.clock,
    )
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith(("/notifications", "/deadlines")) for p in paths)
    assert not hasattr(app.state, "proactive")
