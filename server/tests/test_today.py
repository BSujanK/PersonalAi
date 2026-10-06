"""GET /today answers from a cache that a background job fills; no request waits on Google."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.store.db import Database
from agent.store.keystore import KeyStore
from tests.proactive_support import make_env
from tests.support import START, FakeClock
from tests.test_api import _auth
from tests.test_loop import FakeLLM, say

SLOW_SECONDS = 2.0
PARAMS = {"type": "object", "properties": {}}
LATENCY_BUDGET = 0.5


@dataclass
class Source:
    """A READ tool that sleeps, counts its calls and can be told to fail from a call number."""

    name: str
    sleep: float = 0.0
    fail_from: int | None = None
    calls: int = 0

    def run(self, _args: dict[str, Any]) -> Any:
        self.calls += 1
        time.sleep(self.sleep)
        if self.fail_from is not None and self.calls >= self.fail_from:
            raise RuntimeError("secret upstream detail")
        return [{"title": f"{self.name} #{self.calls}"}]

    def tool(self) -> Tool:
        return Tool(self.name, self.name, PARAMS, ToolKind.READ, self.run)


@dataclass
class TodayApi:
    client: TestClient
    clock: FakeClock
    headers: dict[str, str]
    events: Source
    coursework: Source

    def refresh(self) -> None:
        self.client.app.state.today.refresh()  # type: ignore[attr-defined]

    def today(self) -> dict[str, Any]:
        response = self.client.get("/today", headers=self.headers)
        assert response.status_code == 200
        body: dict[str, Any] = response.json()
        return body


def _api(sleep: float = 0.0, **fail_from: int) -> TodayApi:
    events = Source("calendar_events", sleep, fail_from.get("events"))
    coursework = Source("classroom_coursework", sleep, fail_from.get("deadlines"))
    registry = ToolRegistry()
    registry.register(events.tool())
    registry.register(coursework.tool())
    db = Database(":memory:")
    clock = FakeClock()
    app = create_app(
        Settings(),
        db=db,
        keystore=KeyStore(),
        llm=FakeLLM(say("ok")),
        registry=registry,
        clock=clock,
    )
    client = TestClient(app)
    code = open_pairing_window(db, clock, 300)
    paired = client.post("/pair", json={"code": code, "device_name": "Pixel"}).json()
    return TodayApi(client, clock, _auth(paired), events, coursework)


def test_today_is_fast_after_a_refresh_and_never_calls_the_tools() -> None:
    api = _api(SLOW_SECONDS)
    api.refresh()
    assert (api.events.calls, api.coursework.calls) == (1, 1)
    started = time.perf_counter()
    body = api.today()
    elapsed = time.perf_counter() - started
    assert elapsed < LATENCY_BUDGET, f"/today took {elapsed:.3f}s"
    assert (api.events.calls, api.coursework.calls) == (1, 1)
    assert body["events"] == [{"title": "calendar_events #1"}]
    assert body["deadlines"] == [{"title": "classroom_coursework #1"}]
    assert body["mail"] is None
    assert body["unavailable"] == [] and body["stale"] == []
    assert body["updated_at"] == {
        "mail": None,
        "deadlines": START.isoformat(),
        "events": START.isoformat(),
    }


def test_before_any_refresh_sources_are_unavailable() -> None:
    api = _api()
    body = api.today()
    assert body["events"] is None and body["deadlines"] is None
    assert body["unavailable"] == ["deadlines", "events"]
    assert body["stale"] == []
    assert body["updated_at"] == {"mail": None, "deadlines": None, "events": None}
    assert (api.events.calls, api.coursework.calls) == (0, 0)


def test_a_failing_refresh_keeps_old_data_and_marks_it_stale() -> None:
    api = _api(deadlines=2)
    api.refresh()
    api.clock.advance(timedelta(minutes=1))
    api.refresh()
    body = api.today()
    assert body["deadlines"] == [{"title": "classroom_coursework #1"}]
    assert body["stale"] == ["deadlines"]
    assert body["unavailable"] == []
    assert body["events"] == [{"title": "calendar_events #2"}]
    assert body["updated_at"]["deadlines"] == START.isoformat()
    assert body["updated_at"]["events"] == (START + timedelta(minutes=1)).isoformat()


def test_a_source_that_fails_with_no_data_is_unavailable() -> None:
    api = _api(events=1)
    api.refresh()
    body = api.today()
    assert body["events"] is None
    assert body["unavailable"] == ["events"]
    assert body["stale"] == []
    assert body["deadlines"] == [{"title": "classroom_coursework #1"}]


def test_a_source_recovers_when_a_later_refresh_succeeds() -> None:
    api = _api()
    api.refresh()
    api.coursework.fail_from = 2
    api.refresh()
    assert api.today()["stale"] == ["deadlines"]
    api.coursework.fail_from = None
    api.refresh()
    body = api.today()
    assert body["stale"] == [] and body["deadlines"] == [{"title": "classroom_coursework #3"}]


def test_old_data_is_stale_after_three_refresh_intervals() -> None:
    api = _api()
    api.refresh()
    api.clock.advance(timedelta(minutes=9))  # 3 x the default 3-minute refresh
    assert api.today()["stale"] == []
    api.clock.advance(timedelta(seconds=1))
    body = api.today()
    assert body["stale"] == ["deadlines", "events"]
    assert body["events"] == [{"title": "calendar_events #1"}]


def test_a_failure_is_logged_by_type_only(caplog: Any) -> None:
    api = _api(events=1)
    with caplog.at_level("WARNING"):
        api.refresh()
    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text


def test_write_tools_are_not_a_source() -> None:
    registry = ToolRegistry()
    registry.register(
        Tool("calendar_events", "w", PARAMS, ToolKind.WRITE, lambda _a: [1], preview=lambda _a: "p")
    )
    db = Database(":memory:")
    clock = FakeClock()
    app = create_app(
        Settings(),
        db=db,
        keystore=KeyStore(),
        llm=FakeLLM(say("ok")),
        registry=registry,
        clock=clock,
    )
    app.state.today.refresh()
    snapshot = app.state.today.snapshot()
    assert snapshot == {}


def test_notifications_and_deadlines_never_wait_on_google() -> None:
    env = make_env()
    events = Source("calendar_events", SLOW_SECONDS)
    coursework = Source("classroom_coursework", SLOW_SECONDS)
    registry = ToolRegistry()
    registry.register(events.tool())
    registry.register(coursework.tool())
    app = create_app(
        env.settings,
        db=env.db,
        keystore=KeyStore(),
        llm=FakeLLM(say("hi")),
        registry=registry,
        clock=env.clock,
        proactive=env.services,
    )
    client = TestClient(app)
    code = open_pairing_window(env.db, env.clock, 300)
    headers = _auth(client.post("/pair", json={"code": code, "device_name": "Pixel"}).json())
    for path in ("/notifications", "/deadlines"):
        started = time.perf_counter()
        assert client.get(path, headers=headers).status_code == 200
        assert time.perf_counter() - started < LATENCY_BUDGET
    assert (events.calls, coursework.calls) == (0, 0)
