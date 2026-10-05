from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from agent.core.llm import ChatMessage, LLMResponse
from agent.core.redact import from_model
from tests.test_api import _api, _auth, _pair


class BlockingLLM:
    """Blocks inside the first concurrent turn until released, recording every call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.first_in = threading.Event()
        self.second_in = threading.Event()
        self.release = threading.Event()
        self.block = False
        self._guard = threading.Lock()
        self._concurrent_calls = 0

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        with self._guard:
            self.calls.append([m.content.text for m in messages])
            self._concurrent_calls += 1 if self.block else 0
            ordinal = self._concurrent_calls
        if self.block and ordinal == 1:
            self.first_in.set()
            self.release.wait(10)
        elif self.block and ordinal == 2:
            self.second_in.set()
        return LLMResponse(from_model("ok"), [])


def test_concurrent_turns_on_one_conversation_are_serialised() -> None:
    llm = BlockingLLM()
    api = _api(llm)  # type: ignore[arg-type]
    headers = _auth(_pair(api))
    conversation_id = api.client.post("/chat", headers=headers, json={"message": "start"}).json()[
        "conversation_id"
    ]
    llm.block = True
    statuses: list[int] = []

    def post(text: str) -> None:
        resp = api.client.post(
            "/chat", headers=headers, json={"conversation_id": conversation_id, "message": text}
        )
        statuses.append(resp.status_code)

    first = threading.Thread(target=post, args=("turn-A",))
    first.start()
    assert llm.first_in.wait(10)
    second = threading.Thread(target=post, args=("turn-B",))
    second.start()
    # Without the lock the second turn reaches the model while the first is still blocked.
    llm.second_in.wait(0.5)
    llm.release.set()
    first.join(10)
    second.join(10)

    assert statuses == [200, 200]
    seqs = [r["seq"] for r in api.db.query("SELECT seq FROM messages ORDER BY seq")]
    assert seqs == list(range(1, 7))
    later = llm.calls[-1]
    assert "turn-A" in later
    assert "turn-B" in later
    assert later.index("turn-A") < later.index("turn-B")
