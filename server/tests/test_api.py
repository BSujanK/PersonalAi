from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.connectors.gmail import GmailApi
from agent.core.llm import LLMUnavailable, MissingModelError
from agent.core.policy import expected_signature, signature_message
from agent.mail.services import MailServices
from agent.mail.store import MailStore
from agent.mail.sync import MailSync
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from tests.fakes_gmail import FakeGmailApi
from tests.support import FakeClock, make_registry
from tests.test_loop import FakeLLM, call, say

SEND = {"to": "friend@example.com", "subject": "Hi", "body": "Lunch?"}


@dataclass
class Api:
    app: FastAPI
    client: TestClient
    db: Database
    clock: FakeClock
    executed: list[dict[str, Any]]


def _mail_services(db: Database, clock: FakeClock, keystore: KeyStore) -> MailServices:
    key = keystore.get_or_create_bytes("db_key")
    store = MailStore(db, FieldCipher(key), key, clock)
    api = FakeGmailApi()

    def api_for(_account: str) -> GmailApi:
        return api

    return MailServices(store, MailSync(store, api_for, None, clock, 7), api_for)


def _api(llm: FakeLLM | None = None) -> Api:
    db = Database(":memory:")
    clock = FakeClock()
    keystore = KeyStore()
    executed: list[dict[str, Any]] = []
    app = create_app(
        Settings(owner_emails=("me@example.com",)),
        db=db,
        keystore=keystore,
        llm=llm or FakeLLM(say("hello")),
        registry=make_registry(executed),
        clock=clock,
        mail=_mail_services(db, clock, keystore),
    )
    return Api(app, TestClient(app), db, clock, executed)


def _pair(api: Api) -> dict[str, str]:
    code = open_pairing_window(api.db, api.clock, 300)
    resp = api.client.post("/pair", json={"code": code, "device_name": "Pixel"})
    assert resp.status_code == 200, resp.text
    body: dict[str, str] = resp.json()
    return body


def _auth(paired: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {paired['token']}"}


def _key(paired: dict[str, str]) -> bytes:
    text = paired["approval_key"]
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(paired: dict[str, str], item: dict[str, Any], decision: str) -> str:
    msg = signature_message(item["id"], item["payload_hash"], item["nonce"], decision)
    return expected_signature(_key(paired), msg)


def _flatten(routes: Any, prefix: str = "") -> list[tuple[str, str]]:
    """List (method, path) for every endpoint, descending into included routers."""
    found: list[tuple[str, str]] = []
    for route in routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, prefix + route.path.replace("{action_id}", "abc")))
        elif hasattr(route, "original_router"):
            inner_prefix = prefix + route.include_context.prefix
            found.extend(_flatten(route.original_router.routes, inner_prefix))
        else:
            raise AssertionError(f"unexpected route type {route!r}")
    return found


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    return _flatten(app.routes)


def test_every_route_except_pair_requires_a_device_token() -> None:
    api = _api()
    routes = _routes(api.app)
    assert ("POST", "/pair") in routes
    assert len(routes) >= 7
    assert ("GET", "/mail/digest") in routes
    assert ("POST", "/mail/feedback") in routes
    for method, path in routes:
        if (method, path) == ("POST", "/pair"):
            continue
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
            resp = api.client.request(method, path, headers=headers, json={})
            assert resp.status_code == 401, (method, path, headers)
            assert resp.headers["www-authenticate"] == "Bearer"


def test_docs_are_disabled() -> None:
    api = _api()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert api.client.get(path).status_code in (401, 404)


def test_pair_without_window_is_forbidden() -> None:
    api = _api()
    resp = api.client.post("/pair", json={"code": "x", "device_name": "p"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "pairing unavailable"}


def test_pair_wrong_code_and_five_attempts_close_window() -> None:
    api = _api()
    code = open_pairing_window(api.db, api.clock, 300)
    for _ in range(5):
        resp = api.client.post("/pair", json={"code": "wrong", "device_name": "p"})
        assert resp.status_code == 403
    resp = api.client.post("/pair", json={"code": code, "device_name": "p"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "pairing unavailable"}


def test_pair_success_returns_token_and_key_and_is_single_use() -> None:
    api = _api()
    code = open_pairing_window(api.db, api.clock, 300)
    first = api.client.post("/pair", json={"code": code, "device_name": "Pixel"})
    body = first.json()
    assert first.status_code == 200
    assert len(_key(body)) == 32
    assert "=" not in body["approval_key"]
    assert body["signature_scheme"] == "hmac-sha256:action_id|payload_hash|nonce|decision"
    assert api.client.get("/health", headers=_auth(body)).json() == {"status": "ok"}
    again = api.client.post("/pair", json={"code": code, "device_name": "Other"})
    assert again.status_code == 403
    stored = api.db.query("SELECT token_hash FROM devices")[0]["token_hash"]
    assert stored != body["token"]
    events = [r["event"] for r in api.db.query("SELECT event FROM audit_log")]
    assert events == ["device_paired"]


def test_expired_window_is_refused() -> None:
    api = _api()
    code = open_pairing_window(api.db, api.clock, 300)
    api.clock.advance(timedelta(seconds=301))
    resp = api.client.post("/pair", json={"code": code, "device_name": "p"})
    assert resp.status_code == 403


def test_opening_new_window_closes_previous() -> None:
    api = _api()
    old = open_pairing_window(api.db, api.clock, 300)
    open_pairing_window(api.db, api.clock, 300)
    assert api.client.post("/pair", json={"code": old, "device_name": "p"}).status_code == 403


def test_pair_validates_body() -> None:
    api = _api()
    assert api.client.post("/pair", json={"code": "x", "device_name": ""}).status_code == 422
    assert api.client.post("/pair", json={"code": "x", "device_name": "n" * 65}).status_code == 422


def test_revoked_device_is_unauthorized() -> None:
    api = _api()
    paired = _pair(api)
    api.db.execute("UPDATE devices SET revoked = 1")
    assert api.client.get("/health", headers=_auth(paired)).status_code == 401


def test_full_flow_pair_chat_approve_executes() -> None:
    llm = FakeLLM(call("send_email", SEND), say("I drafted it for you."))
    api = _api(llm)
    paired = _pair(api)
    headers = _auth(paired)
    chat = api.client.post("/chat", headers=headers, json={"message": "Email my friend"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["reply"] == "I drafted it for you."
    assert len(body["pending_action_ids"]) == 1
    assert api.executed == []

    listing = api.client.get("/approvals", headers=headers).json()
    assert [i["id"] for i in listing] == body["pending_action_ids"]
    item = listing[0]
    assert set(item) >= {"id", "tool_name", "preview", "payload_hash", "nonce", "created_at"}
    assert item["expires_at"] > item["created_at"]
    assert api.client.get(f"/approvals/{item['id']}", headers=headers).json()["id"] == item["id"]

    payload = {
        "payload_hash": item["payload_hash"],
        "nonce": item["nonce"],
        "sig": _sig(paired, item, "approve"),
    }
    resp = api.client.post(f"/approvals/{item['id']}/approve", headers=headers, json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"id": item["id"], "status": "executed"}
    assert api.executed == [SEND]
    replay = api.client.post(f"/approvals/{item['id']}/approve", headers=headers, json=payload)
    assert replay.status_code == 409
    assert replay.json() == {"detail": "not_pending"}
    assert api.executed == [SEND]
    assert api.client.get("/approvals", headers=headers).json() == []


def test_reject_flow() -> None:
    api = _api(FakeLLM(call("send_email", SEND), say("drafted")))
    paired = _pair(api)
    headers = _auth(paired)
    api.client.post("/chat", headers=headers, json={"message": "go"})
    item = api.client.get("/approvals", headers=headers).json()[0]
    payload = {
        "payload_hash": item["payload_hash"],
        "nonce": item["nonce"],
        "sig": _sig(paired, item, "reject"),
    }
    resp = api.client.post(f"/approvals/{item['id']}/reject", headers=headers, json=payload)
    assert resp.json()["status"] == "rejected"
    assert api.executed == []


def test_device_token_alone_cannot_approve() -> None:
    api = _api(FakeLLM(call("send_email", SEND), say("drafted")))
    paired = _pair(api)
    headers = _auth(paired)
    api.client.post("/chat", headers=headers, json={"message": "go"})
    item = api.client.get("/approvals", headers=headers).json()[0]
    bogus = {"payload_hash": item["payload_hash"], "nonce": item["nonce"], "sig": "0" * 64}
    resp = api.client.post(f"/approvals/{item['id']}/approve", headers=headers, json=bogus)
    assert resp.status_code == 403
    assert resp.json() == {"detail": "bad_signature"}
    assert api.executed == []
    assert api.client.get(f"/approvals/{item['id']}", headers=headers).json()["status"] == "pending"


def test_approve_expired_and_unknown_status_codes() -> None:
    api = _api(FakeLLM(call("send_email", SEND), say("drafted")))
    paired = _pair(api)
    headers = _auth(paired)
    api.client.post("/chat", headers=headers, json={"message": "go"})
    item = api.client.get("/approvals", headers=headers).json()[0]
    payload = {
        "payload_hash": item["payload_hash"],
        "nonce": item["nonce"],
        "sig": _sig(paired, item, "approve"),
    }
    missing = api.client.post("/approvals/nope/approve", headers=headers, json=payload)
    assert missing.status_code == 404
    assert api.client.get("/approvals/nope", headers=headers).status_code == 404
    api.clock.advance(timedelta(minutes=16))
    late = api.client.post(f"/approvals/{item['id']}/approve", headers=headers, json=payload)
    assert late.status_code == 409 and late.json() == {"detail": "expired"}
    assert api.executed == []


def test_chat_continues_conversation_and_persists_encrypted() -> None:
    llm = FakeLLM(say("first"), say("second"))
    api = _api(llm)
    headers = _auth(_pair(api))
    first = api.client.post(
        "/chat", headers=headers, json={"message": "my card is 4111 1111 1111 1111"}
    ).json()
    second = api.client.post(
        "/chat",
        headers=headers,
        json={"conversation_id": first["conversation_id"], "message": "again"},
    ).json()
    assert second["conversation_id"] == first["conversation_id"]
    assert second["reply"] == "second"
    assert [m.role for m in llm.received[1]] == ["system", "user", "assistant", "user"]
    for batch in llm.received:
        assert all("4111" not in m.content.text for m in batch)
    for row in api.db.query("SELECT content_enc FROM messages"):
        assert b"CARD_1" not in row["content_enc"]
    assert len(api.db.query("SELECT 1 FROM messages")) == 4


def test_chat_unknown_conversation_and_validation() -> None:
    api = _api()
    headers = _auth(_pair(api))
    assert (
        api.client.post(
            "/chat", headers=headers, json={"conversation_id": "nope", "message": "hi"}
        ).status_code
        == 404
    )
    assert api.client.post("/chat", headers=headers, json={"message": ""}).status_code == 422
    assert (
        api.client.post("/chat", headers=headers, json={"message": "x" * 8001}).status_code == 422
    )


def test_chat_llm_unavailable_is_503() -> None:
    def down(_m: Any) -> Any:
        raise LLMUnavailable("down")

    api = _api(FakeLLM(down))
    headers = _auth(_pair(api))
    resp = api.client.post("/chat", headers=headers, json={"message": "hi"})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "llm unavailable"}


def test_chat_llm_not_configured_is_503() -> None:
    def unconfigured(_m: Any) -> Any:
        raise MissingModelError("PERSONALAI_MODEL_PRIMARY is not set")

    api = _api(FakeLLM(unconfigured))
    headers = _auth(_pair(api))
    resp = api.client.post("/chat", headers=headers, json={"message": "hi"})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "llm not configured"}


@pytest.mark.parametrize("path", ["/approvals", "/health"])
def test_get_routes_work_with_token(path: str) -> None:
    api = _api()
    assert api.client.get(path, headers=_auth(_pair(api))).status_code == 200
