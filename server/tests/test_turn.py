"""Turn scopes and masked tool arguments (Tool.rehydrate_args)."""

from __future__ import annotations

from typing import Any

from agent.core.redact import RedactionMap
from agent.core.tools import Tool, ToolKind
from agent.core.turn import current_turn, turn_scope
from tests.support import make_env
from tests.test_loop import OWNER, FakeLLM, _loop, call, say


def test_turn_scope_is_fresh_per_block_and_none_outside() -> None:
    assert current_turn() is None
    with turn_scope() as first:
        assert current_turn() == first
    with turn_scope() as second:
        assert current_turn() == second
    assert first != second
    assert current_turn() is None


def _recording_tool(name: str, seen: list[tuple[Any, str | None]], *, rehydrate: bool) -> Tool:
    def run(args: dict[str, Any]) -> Any:
        seen.append((args, current_turn()))
        return {"ok": True}

    return Tool(
        name=name,
        description="test",
        parameters={"type": "object"},
        kind=ToolKind.READ,
        run=run,
        rehydrate_args=rehydrate,
    )


def test_masked_tool_gets_placeholders_and_normal_tool_gets_values() -> None:
    env = make_env()
    seen_masked: list[tuple[Any, str | None]] = []
    seen_plain: list[tuple[Any, str | None]] = []
    env.registry.register(_recording_tool("masked_tool", seen_masked, rehydrate=False))
    env.registry.register(_recording_tool("plain_tool", seen_plain, rehydrate=True))
    llm = FakeLLM(
        call("masked_tool", {"q": "⟨EMAIL_SELF_1⟩"}, "c1"),
        call("plain_tool", {"q": "⟨EMAIL_SELF_1⟩"}, "c2"),
        say("done"),
    )
    _loop(env, llm).run("conv", [], f"look up {OWNER}", RedactionMap())
    assert seen_masked[0][0] == {"q": "⟨EMAIL_SELF_1⟩"}
    assert seen_plain[0][0] == {"q": OWNER}
    # Both calls ran inside the same turn scope, and the scope ends with the turn.
    assert seen_masked[0][1] is not None
    assert seen_masked[0][1] == seen_plain[0][1]
    assert current_turn() is None


def test_each_owner_message_is_a_new_turn() -> None:
    env = make_env()
    seen: list[tuple[Any, str | None]] = []
    env.registry.register(_recording_tool("masked_tool", seen, rehydrate=False))
    loop = _loop(env, FakeLLM(call("masked_tool", {}), say("done")))
    loop.run("conv", [], "one", RedactionMap())
    loop = _loop(env, FakeLLM(call("masked_tool", {}), say("done")))
    loop.run("conv", [], "two", RedactionMap())
    assert seen[0][1] != seen[1][1]
