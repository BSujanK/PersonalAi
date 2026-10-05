"""Conversation history API (/conversations) and the SSE ``tool`` event."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from agent.api.conversations import DEFAULT_TITLE, make_title
from tests.test_api import SEND, Api, _api, _auth, _pair
from tests.test_chat_stream import _stream
from tests.test_loop import FakeLLM, StreamingFakeLLM, _tool_call, call, say

OWNER = "me@example.com"


def _chat(
    api: Api, headers: dict[str, str], message: str, cid: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"message": message}
    if cid:
        body["conversation_id"] = cid
    resp = api.client.post("/chat", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# -- auth ---------------------------------------------------------------------------------


def test_every_conversation_route_requires_a_device_token() -> None:
    api = _api()
    headers = _auth(_pair(api))
    cid = _chat(api, headers, "hello")["conversation_id"]
    calls = [
        ("GET", "/conversations", None),
        ("GET", f"/conversations/{cid}", None),
        ("PATCH", f"/conversations/{cid}", {"title": "x"}),
        ("DELETE", f"/conversations/{cid}", None),
    ]
    for method, path, body in calls:
        for bad in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
            resp = api.client.request(method, path, headers=bad, json=body)
            assert resp.status_code == 401, (method, path, bad)
    # nothing was renamed or deleted by the rejected calls
    assert api.client.get(f"/conversations/{cid}", headers=headers).json()["title"] == "hello"


def test_revoked_device_cannot_read_history() -> None:
    api = _api()
    paired = _pair(api)
    headers = _auth(paired)
    _chat(api, headers, "hello")
    api.db.execute("UPDATE devices SET revoked = 1")
    assert api.client.get("/conversations", headers=headers).status_code == 401


# -- list ---------------------------------------------------------------------------------


def test_list_is_newest_first_with_auto_title_and_rehydrated_preview() -> None:
    api = _api(FakeLLM(say("Sure.\nSent to ⟨EMAIL_SELF_1⟩ just now.")))
    headers = _auth(_pair(api))
    first = _chat(api, headers, f"Email {OWNER} about **lunch**")["conversation_id"]
    api.clock.advance(timedelta(minutes=5))
    second = _chat(api, headers, "What is due this week?")["conversation_id"]
    page = api.client.get("/conversations", headers=headers).json()
    assert [i["id"] for i in page["items"]] == [second, first]
    assert page["next_cursor"] is None
    assert page["items"][0]["title"] == "What is due this week?"
    assert page["items"][1]["title"] == f"Email {OWNER} about lunch"  # markup stripped
    # last line, rehydrated for the phone
    assert page["items"][1]["preview"] == f"Sent to {OWNER} just now."
    assert set(page["items"][0]) == {"id", "title", "updated_at", "preview"}


def test_activity_in_an_old_conversation_moves_it_to_the_top() -> None:
    api = _api()
    headers = _auth(_pair(api))
    first = _chat(api, headers, "one")["conversation_id"]
    api.clock.advance(timedelta(minutes=1))
    second = _chat(api, headers, "two")["conversation_id"]
    api.clock.advance(timedelta(minutes=1))
    _chat(api, headers, "again", first)
    ids = [i["id"] for i in api.client.get("/conversations", headers=headers).json()["items"]]
    assert ids == [first, second]


def test_list_paginates_with_cursor() -> None:
    api = _api()
    headers = _auth(_pair(api))
    made = []
    for n in range(5):
        api.clock.advance(timedelta(minutes=1))
        made.append(_chat(api, headers, f"chat {n}")["conversation_id"])
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = api.client.get("/conversations", headers=headers, params=params).json()
        seen.extend(i["id"] for i in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(reversed(made))
    assert api.client.get("/conversations?limit=0", headers=headers).status_code == 422
    assert api.client.get("/conversations?limit=101", headers=headers).status_code == 422


def test_list_search_matches_titles_only() -> None:
    api = _api()
    headers = _auth(_pair(api))
    _chat(api, headers, "Spending in September")
    api.clock.advance(timedelta(minutes=1))
    _chat(api, headers, "Classroom deadlines")
    found = api.client.get("/conversations", headers=headers, params={"q": "spend"}).json()
    assert [i["title"] for i in found["items"]] == ["Spending in September"]
    none = api.client.get("/conversations", headers=headers, params={"q": "zzz"}).json()
    assert none["items"] == []


def test_empty_list() -> None:
    api = _api()
    page = api.client.get("/conversations", headers=_auth(_pair(api))).json()
    assert page == {"items": [], "next_cursor": None}


def test_make_title() -> None:
    assert make_title("  hi   there \n now ") == "hi there now"
    assert make_title("") == DEFAULT_TITLE
    assert make_title("###") == DEFAULT_TITLE
    long = make_title("word " * 40)
    assert len(long) <= 61 and long.endswith("…")
    assert make_title("x" * 200) == "x" * 60 + "…"


# -- detail -------------------------------------------------------------------------------


def test_detail_rehydrates_for_display_only() -> None:
    llm = FakeLLM(say("Noted, ⟨EMAIL_SELF_1⟩."), say("Still ⟨EMAIL_SELF_1⟩."))
    api = _api(llm)
    headers = _auth(_pair(api))
    cid = _chat(api, headers, f"My address is {OWNER}")["conversation_id"]
    detail = api.client.get(f"/conversations/{cid}", headers=headers).json()
    assert [(m["role"], m["text"]) for m in detail["messages"]] == [
        ("user", f"My address is {OWNER}"),
        ("assistant", f"Noted, {OWNER}."),
    ]
    assert detail["title"] == f"My address is {OWNER}"
    # Opening the conversation changes nothing about what the LLM receives next turn.
    _chat(api, headers, "and again", cid)
    sent = [m.content.text for m in llm.received[-1]]
    assert any("⟨EMAIL_SELF_1⟩" in t for t in sent)
    assert not any(OWNER in t for t in sent)


def test_detail_reports_tools_and_pending_actions_per_turn() -> None:
    llm = FakeLLM(
        call("read_mail", {}),
        call("send_email", SEND),
        say("I drafted it."),
        call("wipe_disk", {}),
        say("Could not."),
    )
    api = _api(llm)
    headers = _auth(_pair(api))
    cid = _chat(api, headers, "mail then send")["conversation_id"]
    _chat(api, headers, "wipe", cid)
    messages = api.client.get(f"/conversations/{cid}", headers=headers).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    first = messages[1]
    assert first["text"] == "I drafted it."
    assert first["tools"] == [
        {"name": "read_mail", "status": "finished"},
        {"name": "send_email", "status": "finished"},
    ]
    rows = api.db.query("SELECT id FROM pending_actions")
    assert first["pending_action_ids"] == [rows[0]["id"]]
    second = messages[3]
    assert second["tools"] == [{"name": "wipe_disk", "status": "failed"}]
    assert second["pending_action_ids"] == []
    assert messages[0]["tools"] == [] and messages[0]["pending_action_ids"] == []
    # Tool arguments and results never appear in the display payload.
    text = json.dumps(messages)
    assert "friend@example.com" not in text and "Lunch?" not in text and "sender@" not in text


def test_detail_never_shows_malformed_tool_names() -> None:
    api = _api(FakeLLM(call("<script>alert(1)</script>", {}), say("ok")))
    headers = _auth(_pair(api))
    cid = _chat(api, headers, "hi")["conversation_id"]
    messages = api.client.get(f"/conversations/{cid}", headers=headers).json()["messages"]
    assert messages[1]["tools"] == [{"name": "unknown", "status": "failed"}]


def test_detail_unknown_is_404() -> None:
    api = _api()
    resp = api.client.get("/conversations/nope", headers=_auth(_pair(api)))
    assert resp.status_code == 404


# -- rename and delete --------------------------------------------------------------------


def test_rename_persists_and_survives_more_chat() -> None:
    api = _api()
    headers = _auth(_pair(api))
    cid = _chat(api, headers, "first words")["conversation_id"]
    resp = api.client.patch(
        f"/conversations/{cid}", headers=headers, json={"title": "  Trip plan "}
    )
    assert resp.status_code == 200 and resp.json()["title"] == "Trip plan"
    _chat(api, headers, "more", cid)
    assert api.client.get(f"/conversations/{cid}", headers=headers).json()["title"] == "Trip plan"
    items = api.client.get("/conversations", headers=headers).json()["items"]
    assert items[0]["title"] == "Trip plan"
    # the title is encrypted at rest
    blob = api.db.query("SELECT title_enc FROM conversation_titles")[0]["title_enc"]
    assert b"Trip plan" not in bytes(blob)


def test_rename_validation() -> None:
    api = _api()
    headers = _auth(_pair(api))
    cid = _chat(api, headers, "hello")["conversation_id"]
    for body in ({"title": ""}, {"title": "   "}, {}, {"title": "x" * 201}):
        resp = api.client.patch(f"/conversations/{cid}", headers=headers, json=body)
        assert resp.status_code == 422, body
    missing = api.client.patch("/conversations/nope", headers=headers, json={"title": "a"})
    assert missing.status_code == 404


def test_delete_removes_messages_but_keeps_approval_records() -> None:
    api = _api(FakeLLM(call("send_email", SEND), say("Proposed.")))
    headers = _auth(_pair(api))
    cid = _chat(api, headers, "send it")["conversation_id"]
    other = _chat(api, headers, "keep me")["conversation_id"]
    assert api.client.delete(f"/conversations/{cid}", headers=headers).status_code == 204
    assert api.client.get(f"/conversations/{cid}", headers=headers).status_code == 404
    assert api.client.delete(f"/conversations/{cid}", headers=headers).status_code == 404
    assert api.db.query("SELECT 1 FROM messages WHERE conversation_id = ?", (cid,)) == []
    assert api.db.query("SELECT 1 FROM conversation_titles WHERE conversation_id = ?", (cid,)) == []
    ids = [i["id"] for i in api.client.get("/conversations", headers=headers).json()["items"]]
    assert ids == [other]
    # The pending approval is not silently dropped.
    assert [r["status"] for r in api.db.query("SELECT status FROM pending_actions")] == ["pending"]
    # And the deleted conversation can no longer be continued.
    resp = api.client.post("/chat", headers=headers, json={"conversation_id": cid, "message": "x"})
    assert resp.status_code == 404


# -- SSE tool events ----------------------------------------------------------------------


def _tool_events(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [data for name, data in events if name == "tool"]


def test_stream_emits_tool_started_and_finished_with_names_only() -> None:
    llm = StreamingFakeLLM(
        ([], [_tool_call("read_mail", {})]),
        ([], [_tool_call("send_email", SEND)]),
        (["Done."], []),
    )
    api = _api(llm)  # type: ignore[arg-type]
    events = _stream(api, _auth(_pair(api)), {"message": "go"})
    assert _tool_events(events) == [
        {"name": "read_mail", "status": "started"},
        {"name": "read_mail", "status": "finished"},
        {"name": "send_email", "status": "started"},
        {"name": "send_email", "status": "finished"},
    ]
    assert events[-1][0] == "done"
    raw = json.dumps(events)
    assert "friend@example.com" not in raw and "Lunch?" not in raw and "sender@example" not in raw


def test_stream_tool_event_order_relative_to_other_events() -> None:
    llm = StreamingFakeLLM(([], [_tool_call("read_mail", {})]), (["ok"], []))
    api = _api(llm)  # type: ignore[arg-type]
    names = [n for n, _ in _stream(api, _auth(_pair(api)), {"message": "go"})]
    assert names == ["start", "tool", "tool", "token", "done"]


def test_stream_tool_failures_and_unknown_names() -> None:
    llm = StreamingFakeLLM(
        ([], [_tool_call("wipe_disk <b>", {})]),
        (["Done."], []),
    )
    api = _api(llm)  # type: ignore[arg-type]
    events = _stream(api, _auth(_pair(api)), {"message": "go"})
    assert _tool_events(events) == [
        {"name": "unknown", "status": "started"},
        {"name": "unknown", "status": "failed"},
    ]
    assert "wipe_disk" not in json.dumps(events)


def test_json_path_has_no_tool_events_and_is_unchanged() -> None:
    api = _api(FakeLLM(call("read_mail", {}), say("ok")))
    resp = api.client.post("/chat", headers=_auth(_pair(api)), json={"message": "go"})
    assert resp.status_code == 200
    assert set(resp.json()) == {"conversation_id", "reply", "pending_action_ids"}
    assert "event:" not in resp.text
