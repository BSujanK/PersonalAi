"""M5 server side: phone WRITE tools, the device-command queue, push, /today and the
cross-language approval-signature vectors shared with the mobile app."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.core.policy import expected_signature, signature_message
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.phone.commands import CommandQueue
from agent.phone.push import PushNotifier, pending_text
from agent.phone.tools import register_phone_tools
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from tests.support import START, FakeClock
from tests.test_loop import FakeLLM, call, say

VECTORS = (
    Path(__file__).resolve().parents[2] / "shared" / "test-vectors" / "approval-signature.json"
)
PUSH_TOKEN = "ExponentPushToken[abcDEF123_-xyz]"


# --- shared signature vectors ----------------------------------------------------------------


def test_shared_signature_vectors_match_policy() -> None:
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    text = data["approval_key_b64url"]
    key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    assert len(key) == 32
    assert len(data["cases"]) >= 3
    for case in data["cases"]:
        msg = signature_message(
            case["action_id"], case["payload_hash"], case["nonce"], case["decision"]
        )
        assert msg.decode() == case["message"]
        assert expected_signature(key, msg) == case["sig"]


# --- tools -----------------------------------------------------------------------------------


def _tools() -> tuple[ToolRegistry, CommandQueue, FakeClock]:
    db = Database(":memory:")
    clock = FakeClock()
    queue = CommandQueue(db, FieldCipher(bytes(32)), clock)
    registry = ToolRegistry()
    register_phone_tools(registry, queue, clock)
    return registry, queue, clock


def _tool(registry: ToolRegistry, name: str) -> Tool:
    tool = registry.get(name)
    assert tool is not None
    return tool


def test_phone_tools_are_write_tools() -> None:
    registry, _, _ = _tools()
    for name in ("phone_set_alarm", "phone_set_timer", "phone_reminder"):
        assert registry.kind_of(name) is ToolKind.WRITE


def test_alarm_preview_and_executor() -> None:
    registry, queue, clock = _tools()
    tool = _tool(registry, "phone_set_alarm")
    args = {"hour": 7, "minute": 5, "label": "Wake up", "days": [2, 6]}
    assert tool.preview is not None
    assert tool.preview(args) == (
        "Set an alarm on your phone for 07:05, repeating Mon, Fri labelled “Wake up”."
    )
    tool.run(args)
    [cmd] = queue.queued()
    assert cmd.kind == "set_alarm"
    assert cmd.params == {"hour": 7, "minute": 5, "label": "Wake up", "days": [2, 6]}
    assert cmd.expires_at == clock() + timedelta(hours=24)


@pytest.mark.parametrize(
    "args",
    [
        {"hour": 24, "minute": 0},
        {"hour": -1, "minute": 0},
        {"hour": 7, "minute": 60},
        {"hour": True, "minute": 0},
        {"hour": 7, "minute": 0, "days": [0]},
        {"hour": 7, "minute": 0, "days": [1, 1]},
        {"hour": 7, "minute": 0, "days": []},
        {"hour": 7, "minute": 0, "label": "x" * 61},
        {"hour": 7, "minute": 0, "label": "two\u2028lines"},
    ],
)
def test_alarm_rejects_bad_arguments(args: dict[str, Any]) -> None:
    registry, queue, _ = _tools()
    tool = _tool(registry, "phone_set_alarm")
    assert tool.preview is not None
    with pytest.raises(ValueError):
        tool.preview(args)
    with pytest.raises(ValueError):
        tool.run(args)
    assert queue.queued() == []


def test_timer_expires_when_it_would_have_rung() -> None:
    registry, queue, clock = _tools()
    tool = _tool(registry, "phone_set_timer")
    assert tool.preview is not None
    assert tool.preview({"seconds": 3725}) == "Start a 1 h 2 min 5 s timer on your phone."
    tool.run({"seconds": 600, "label": "Tea"})
    assert [c.params for c in queue.queued()] == [{"seconds": 600, "label": "Tea"}]
    clock.advance(timedelta(seconds=600))
    assert queue.queued() == []
    with pytest.raises(ValueError):
        tool.run({"seconds": 0})
    with pytest.raises(ValueError):
        tool.run({"seconds": 86401})


def test_reminder_needs_offset_and_future_time() -> None:
    registry, queue, clock = _tools()
    tool = _tool(registry, "phone_reminder")
    assert tool.preview is not None
    at = (clock() + timedelta(hours=2)).isoformat()
    assert tool.preview({"at": at, "text": "Pay fees"}) == (
        f"Remind you on your phone at {at}:\nPay fees"
    )
    tool.run({"at": at, "text": "Pay fees"})
    [cmd] = queue.queued()
    assert cmd.params == {"at": at, "text": "Pay fees"}
    for bad in (
        {"at": "2026-10-05T20:00:00", "text": "x"},  # no offset
        {"at": (clock() - timedelta(minutes=1)).isoformat(), "text": "x"},
        {"at": (clock() + timedelta(days=400)).isoformat(), "text": "x"},
        {"at": "tomorrow", "text": "x"},
        {"at": at, "text": "  "},
        {"at": at, "text": "y" * 201},
    ):
        with pytest.raises(ValueError):
            tool.preview(bad)


# --- API -------------------------------------------------------------------------------------


@dataclass
class PhoneApi:
    client: TestClient
    db: Database
    clock: FakeClock
    headers: dict[str, str]
    key: bytes
    sent: list[list[dict[str, str]]]


def _phone_api(
    llm: FakeLLM | None = None, *, push: str = "off", registry: ToolRegistry | None = None
) -> PhoneApi:
    db = Database(":memory:")
    clock = FakeClock()
    sent: list[list[dict[str, str]]] = []
    app = create_app(
        Settings(push=push),
        db=db,
        keystore=KeyStore(),
        llm=llm or FakeLLM(say("ok")),
        registry=registry or ToolRegistry(),
        clock=clock,
    )
    # Deliver pushes inline to a recorder instead of the network.
    app.state.push = PushNotifier(
        db, app.state.keystore, enabled=push == "expo", sender=sent.append, background=False
    )
    client = TestClient(app)
    code = open_pairing_window(db, clock, 300)
    paired = client.post("/pair", json={"code": code, "device_name": "Pixel"}).json()
    text = paired["approval_key"]
    return PhoneApi(
        client,
        db,
        clock,
        {"Authorization": f"Bearer {paired['token']}"},
        base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)),
        sent,
    )


def _approve(api: PhoneApi, item: dict[str, Any]) -> Any:
    msg = signature_message(item["id"], item["payload_hash"], item["nonce"], "approve")
    return api.client.post(
        f"/approvals/{item['id']}/approve",
        headers=api.headers,
        json={
            "payload_hash": item["payload_hash"],
            "nonce": item["nonce"],
            "sig": expected_signature(api.key, msg),
        },
    )


def test_alarm_flow_queues_a_command_only_after_approval() -> None:
    alarm = {"hour": 6, "minute": 30, "label": "Gym"}
    api = _phone_api(FakeLLM(call("phone_set_alarm", alarm), say("Approve it on your phone.")))
    api.client.post("/chat", headers=api.headers, json={"message": "alarm 6:30 for gym"})
    assert api.client.get("/device/commands", headers=api.headers).json() == {"commands": []}

    [item] = api.client.get("/approvals", headers=api.headers).json()
    assert item["tool_name"] == "phone_set_alarm"
    assert item["preview"] == "Set an alarm on your phone for 06:30 labelled “Gym”."
    assert _approve(api, item).json()["status"] == "executed"

    [cmd] = api.client.get("/device/commands", headers=api.headers).json()["commands"]
    assert cmd["kind"] == "set_alarm"
    assert cmd["params"] == alarm
    ack = api.client.post(
        f"/device/commands/{cmd['id']}/ack", headers=api.headers, json={"result": "done"}
    )
    assert ack.json() == {"id": cmd["id"], "status": "done"}
    assert api.client.get("/device/commands", headers=api.headers).json() == {"commands": []}
    again = api.client.post(
        f"/device/commands/{cmd['id']}/ack", headers=api.headers, json={"result": "done"}
    )
    assert again.status_code == 409
    missing = api.client.post(
        "/device/commands/nope/ack", headers=api.headers, json={"result": "failed"}
    )
    assert missing.status_code == 404
    bad = api.client.post(
        f"/device/commands/{cmd['id']}/ack", headers=api.headers, json={"result": "maybe"}
    )
    assert bad.status_code == 422


def test_command_params_are_encrypted_at_rest() -> None:
    api = _phone_api()
    queue = CommandQueue(api.db, FieldCipher(bytes(32)), api.clock)
    queue.enqueue("reminder", {"at": "2026-10-06T07:00:00+05:30", "text": "Secret plan"}, START)
    raw = api.db.query("SELECT params_enc FROM device_commands")[0][0]
    assert b"Secret plan" not in raw


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/device/commands"),
        ("post", "/device/commands/abc/ack"),
        ("put", "/device/push-token"),
        ("delete", "/device/push-token"),
        ("get", "/today"),
    ],
)
def test_device_routes_need_the_token(method: str, path: str) -> None:
    api = _phone_api()
    assert getattr(api.client, method)(path).status_code == 401


def test_push_is_content_free_and_off_by_default() -> None:
    send = {"hour": 7, "minute": 0, "label": "Exam at 9, bring hall ticket"}
    api = _phone_api(FakeLLM(call("phone_set_alarm", send), say("ok")))
    api.client.put("/device/push-token", headers=api.headers, json={"token": PUSH_TOKEN})
    api.client.post("/chat", headers=api.headers, json={"message": "alarm"})
    assert api.sent == []

    api = _phone_api(FakeLLM(call("phone_set_alarm", send), say("ok")), push="expo")
    bad = api.client.put("/device/push-token", headers=api.headers, json={"token": "nope"})
    assert bad.status_code == 422
    resp = api.client.put("/device/push-token", headers=api.headers, json={"token": PUSH_TOKEN})
    assert resp.status_code == 200
    api.client.post("/chat", headers=api.headers, json={"message": "alarm"})
    assert api.sent == [
        [
            {
                "to": PUSH_TOKEN,
                "title": "PersonalAi",
                "body": "1 approval pending",
                "priority": "high",
            }
        ]
    ]
    assert "hall ticket" not in json.dumps(api.sent)

    api.client.delete("/device/push-token", headers=api.headers)
    api.sent.clear()
    api.client.post("/chat", headers=api.headers, json={"message": "alarm"})
    assert api.sent == []


def test_push_failure_never_breaks_a_proposal() -> None:
    def boom(_messages: list[dict[str, str]]) -> None:
        raise OSError("offline")

    api = _phone_api(FakeLLM(call("phone_set_timer", {"seconds": 60}), say("ok")), push="expo")
    api.client.put("/device/push-token", headers=api.headers, json={"token": PUSH_TOKEN})
    api.client.app.state.push = PushNotifier(  # type: ignore[attr-defined]
        api.db,
        api.client.app.state.keystore,
        enabled=True,
        sender=boom,
        background=False,  # type: ignore[attr-defined]
    )
    resp = api.client.post("/chat", headers=api.headers, json={"message": "timer"})
    assert resp.status_code == 200
    assert len(resp.json()["pending_action_ids"]) == 1


def test_pending_text() -> None:
    assert pending_text(1) == "1 approval pending"
    assert pending_text(3) == "3 approvals pending"


def test_today_reports_configured_sources_and_failures() -> None:
    registry = ToolRegistry()

    def events(args: dict[str, Any]) -> Any:
        assert args == {"days": 2, "limit": 20}
        return [{"account": "me@example.com", "summary": "Lab", "start": "2026-10-05T15:00"}]

    def coursework(_args: dict[str, Any]) -> Any:
        raise RuntimeError("classroom down")

    params = {"type": "object", "properties": {}}
    registry.register(Tool("calendar_events", "e", params, ToolKind.READ, events))
    registry.register(Tool("classroom_coursework", "c", params, ToolKind.READ, coursework))
    api = _phone_api(registry=registry)
    body = api.client.get("/today", headers=api.headers).json()
    assert body["mail"] is None
    assert body["events"][0]["summary"] == "Lab"
    assert body["deadlines"] is None
    assert body["unavailable"] == ["classroom_coursework"]
    assert body["generated_at"] == START.isoformat()


def test_today_with_nothing_configured() -> None:
    api = _phone_api()
    body = api.client.get("/today", headers=api.headers).json()
    assert body == {
        "generated_at": START.isoformat(),
        "mail": None,
        "deadlines": None,
        "events": None,
        "unavailable": [],
    }


def _counting_registry() -> tuple[ToolRegistry, list[str]]:
    registry = ToolRegistry()
    calls: list[str] = []

    def run(name: str, result: Any) -> Any:
        def inner(_args: dict[str, Any]) -> Any:
            calls.append(name)
            return result

        return inner

    params = {"type": "object", "properties": {}}
    registry.register(Tool("calendar_events", "e", params, ToolKind.READ, run("events", [])))
    registry.register(Tool("classroom_coursework", "c", params, ToolKind.READ, run("work", [])))
    return registry, calls


def test_today_sections_return_only_what_was_asked_and_skip_other_connectors() -> None:
    registry, calls = _counting_registry()
    api = _phone_api(registry=registry)
    cases = {
        "mail": {"mail"},
        "events": {"events"},
        "deadlines": {"deadlines"},
        "events,mail": {"events", "mail"},
        "mail,mail": {"mail"},
        "deadlines,events,mail": {"deadlines", "events", "mail"},
    }
    for query, keys in cases.items():
        calls.clear()
        body = api.client.get(f"/today?sections={query}", headers=api.headers).json()
        assert set(body) == {"generated_at", "unavailable", *keys}, query
        assert body["generated_at"] == START.isoformat() and body["unavailable"] == []
        expected_calls = {"events": ["events"], "deadlines": ["work"]}
        assert sorted(calls) == sorted(c for k in keys for c in expected_calls.get(k, [])), query


def test_today_section_failure_is_reported_only_for_that_section() -> None:
    registry = ToolRegistry()

    def boom(_args: dict[str, Any]) -> Any:
        raise RuntimeError("classroom down")

    params = {"type": "object", "properties": {}}
    registry.register(Tool("classroom_coursework", "c", params, ToolKind.READ, boom))
    api = _phone_api(registry=registry)
    body = api.client.get("/today?sections=deadlines", headers=api.headers).json()
    assert body == {
        "generated_at": START.isoformat(),
        "deadlines": None,
        "unavailable": ["classroom_coursework"],
    }


@pytest.mark.parametrize(
    "query", ["", "news", "mail,news", "mail,", ",mail", "Mail", "mail%20", "mail,,events"]
)
def test_today_rejects_unknown_or_empty_sections(query: str) -> None:
    registry, calls = _counting_registry()
    api = _phone_api(registry=registry)
    response = api.client.get(f"/today?sections={query}", headers=api.headers)
    assert response.status_code == 422
    assert calls == []


def test_today_without_sections_calls_every_connector() -> None:
    registry, calls = _counting_registry()
    api = _phone_api(registry=registry)
    body = api.client.get("/today", headers=api.headers).json()
    assert set(body) == {"generated_at", "mail", "deadlines", "events", "unavailable"}
    assert sorted(calls) == ["events", "work"]
