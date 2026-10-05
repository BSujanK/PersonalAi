from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from agent.core.llm import ChatMessage, LLMResponse, LLMUnavailable, MissingApiKeyError
from agent.core.redact import Redacted, from_model
from tests.test_api import SEND, Api, _api, _auth, _pair
from tests.test_loop import FakeLLM, StreamingFakeLLM, _tool_call, say

SSE = {"Accept": "text/event-stream"}


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        if not block:
            continue
        lines = block.split("\n")
        assert len(lines) == 2 and lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def _stream(
    api: Api, headers: dict[str, str], body: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    resp = api.client.post("/chat", headers={**headers, **SSE}, json=body)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    return parse_sse(resp.text)


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


def _tokens(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [data["text"] for name, data in events if name == "token"]


def _counts(api: Api) -> tuple[int, int]:
    conversations = api.db.query("SELECT COUNT(*) AS n FROM conversations")[0]["n"]
    messages = api.db.query("SELECT COUNT(*) AS n FROM messages")[0]["n"]
    return int(conversations), int(messages)


def test_stream_rehydrates_placeholder_split_across_chunks() -> None:
    llm = StreamingFakeLLM((["Sent to ⟨EM", "AIL_SELF", "_1⟩ ", "now."], []))
    api = _api(llm)  # type: ignore[arg-type]
    events = _stream(api, _auth(_pair(api)), {"message": "Email me@example.com"})
    assert _names(events)[0] == "start" and _names(events)[-1] == "done"
    done = events[-1][1]
    assert events[0][1] == {"conversation_id": done["conversation_id"]}
    assert "".join(_tokens(events)) == done["reply"] == "Sent to me@example.com now."
    assert all("⟨" not in t for t in _tokens(events))
    assert set(done) == {"conversation_id", "reply", "pending_action_ids"}
    assert done["pending_action_ids"] == []


def test_stream_tool_step_then_answer_emits_reset() -> None:
    llm = StreamingFakeLLM(
        (["Checking."], [_tool_call("read_mail", {})]),
        (["Nothing ", "new."], []),
    )
    api = _api(llm)  # type: ignore[arg-type]
    events = _stream(api, _auth(_pair(api)), {"message": "mail?"})
    assert _names(events) == ["start", "token", "reset", "token", "token", "done"]
    assert events[2][1] == {}
    assert events[-1][1]["reply"] == "Nothing new."


def test_stream_write_tool_call_creates_pending_action() -> None:
    llm = StreamingFakeLLM(([], [_tool_call("send_email", SEND)]), (["Proposed."], []))
    api = _api(llm)  # type: ignore[arg-type]
    done = _stream(api, _auth(_pair(api)), {"message": "send it"})[-1][1]
    assert len(done["pending_action_ids"]) == 1
    rows = api.db.query("SELECT id FROM pending_actions")
    assert [r["id"] for r in rows] == done["pending_action_ids"]
    assert api.executed == []


def test_stream_with_non_streaming_llm_emits_one_token_then_done() -> None:
    api = _api(FakeLLM(say("Hello ⟨EMAIL_SELF_1⟩")))
    events = _stream(api, _auth(_pair(api)), {"message": "hi me@example.com"})
    assert _names(events) == ["start", "token", "done"]
    assert events[1][1] == {"text": "Hello me@example.com"}
    assert events[2][1]["reply"] == "Hello me@example.com"


class _FailingLLM:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def complete(self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]) -> Any:
        raise self._exc

    def stream_complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: Callable[[Redacted], None],
        on_reset: Callable[[], None],
    ) -> Any:
        on_delta(from_model("partial"))
        raise self._exc


@pytest.mark.parametrize(
    ("exc", "detail"),
    [
        (LLMUnavailable("down"), "llm unavailable"),
        (MissingApiKeyError("no key"), "llm not configured"),
        (RuntimeError("secret text in message"), "internal error"),
    ],
)
def test_stream_failure_emits_error_and_persists_nothing(exc: Exception, detail: str) -> None:
    api = _api(_FailingLLM(exc))  # type: ignore[arg-type]
    events = _stream(api, _auth(_pair(api)), {"message": "hi"})
    assert _names(events) == ["start", "token", "error"]
    assert events[-1][1] == {"detail": detail}
    assert _counts(api) == (0, 0)


def test_stream_unknown_conversation_is_404_json() -> None:
    api = _api()
    resp = api.client.post(
        "/chat",
        headers={**_auth(_pair(api)), **SSE},
        json={"conversation_id": "nope", "message": "hi"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "conversation not found"}


def test_stream_requires_auth_and_validates() -> None:
    api = _api()
    assert api.client.post("/chat", headers=SSE, json={"message": "hi"}).status_code == 401
    resp = api.client.post("/chat", headers={**_auth(_pair(api)), **SSE}, json={"message": ""})
    assert resp.status_code == 422


def test_stream_continues_an_existing_conversation() -> None:
    api = _api(StreamingFakeLLM((["ok"], [])))  # type: ignore[arg-type]
    headers = _auth(_pair(api))
    first = _stream(api, headers, {"message": "one"})[-1][1]
    second = _stream(api, headers, {"conversation_id": first["conversation_id"], "message": "two"})[
        -1
    ][1]
    assert second["conversation_id"] == first["conversation_id"]
    assert _counts(api) == (1, 4)


def test_json_path_still_works_with_and_without_accept() -> None:
    api = _api(FakeLLM(say("hello")))
    headers = _auth(_pair(api))
    for extra in ({"Accept": "application/json"}, {}):
        resp = api.client.post("/chat", headers={**headers, **extra}, json={"message": "hi"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["reply"] == "hello"


def test_json_path_llm_unavailable_is_503() -> None:
    api = _api(_FailingLLM(LLMUnavailable("down")))  # type: ignore[arg-type]
    resp = api.client.post("/chat", headers=_auth(_pair(api)), json={"message": "hi"})
    assert resp.status_code == 503 and resp.json() == {"detail": "llm unavailable"}


class _BlockingStreamLLM:
    def __init__(self) -> None:
        self.first_in = threading.Event()
        self.second_in = threading.Event()
        self.release = threading.Event()
        self.block = False
        self._guard = threading.Lock()
        self._calls = 0

    def complete(self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]) -> Any:
        raise AssertionError("streaming path expected")

    def stream_complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: Callable[[Redacted], None],
        on_reset: Callable[[], None],
    ) -> LLMResponse:
        with self._guard:
            self._calls += 1 if self.block else 0
            ordinal = self._calls
        if self.block and ordinal == 1:
            self.first_in.set()
            self.release.wait(10)
        elif self.block and ordinal == 2:
            self.second_in.set()
        on_delta(from_model("ok"))
        return LLMResponse(from_model("ok"), [])


def test_concurrent_streaming_turns_are_serialised() -> None:
    llm = _BlockingStreamLLM()
    api = _api(llm)  # type: ignore[arg-type]
    headers = _auth(_pair(api))
    conversation_id = _stream(api, headers, {"message": "start"})[-1][1]["conversation_id"]
    llm.block = True
    results: list[list[str]] = []

    def post(text: str) -> None:
        events = _stream(api, headers, {"conversation_id": conversation_id, "message": text})
        results.append(_names(events))

    first = threading.Thread(target=post, args=("turn-A",))
    first.start()
    assert llm.first_in.wait(10)
    second = threading.Thread(target=post, args=("turn-B",))
    second.start()
    # Without the lock the second turn would reach the model while the first is still blocked.
    assert not llm.second_in.wait(0.5)
    llm.release.set()
    first.join(10)
    second.join(10)

    assert results == [["start", "token", "done"]] * 2
    seqs = [r["seq"] for r in api.db.query("SELECT seq FROM messages ORDER BY seq")]
    assert seqs == list(range(1, 7))
