from __future__ import annotations

from typing import Any

import pytest

from agent.core.policy import (
    MAX_PENDING_ACTIONS,
    ApprovalRequest,
    Decision,
    canonical_payload,
    check_approval,
    evaluate_tool_call,
    payload_hash,
)
from agent.core.tools import ForbiddenToolError, Tool, ToolKind, ToolRegistry
from tests.support import make_env, make_registry, request_for


def _tool(name: str, kind: ToolKind = ToolKind.READ, **kw: Any) -> Tool:
    return Tool(
        name=name,
        description="d",
        parameters={"type": "object", "properties": {}},
        kind=kind,
        run=lambda _a: None,
        **kw,
    )


@pytest.mark.parametrize(
    "name",
    [
        "groww_place_order",
        "place_groww_order",
        "broker_buy",
        "sell_stock",
        "demat_cancel_order",
        "trade_modify",
        "stock_order",
    ],
)
def test_forbidden_tool_names(name: str) -> None:
    with pytest.raises(ForbiddenToolError):
        ToolRegistry().register(_tool(name))


@pytest.mark.parametrize("name", ["spend_summary", "list_orders_in_mail", "read_mail"])
def test_allowed_tool_names(name: str) -> None:
    ToolRegistry().register(_tool(name))


@pytest.mark.parametrize("name", ["A", "a", "1abc", "bad-name", "x" * 65, ""])
def test_invalid_names_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="invalid tool name"):
        ToolRegistry().register(_tool(name))


def test_duplicate_and_write_without_preview_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_tool("abc"))
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(_tool("abc"))
    with pytest.raises(ValueError, match="preview"):
        reg.register(_tool("wr", ToolKind.WRITE))


def test_schemas_and_executor_access() -> None:
    reg = make_registry([])
    names = [s["function"]["name"] for s in reg.schemas()]
    assert names == ["send_email", "read_mail"]
    assert reg.kind_of("send_email") is ToolKind.WRITE
    assert reg.kind_of("nope") is None
    with pytest.raises(KeyError):
        reg.executor_for_approved("read_mail")
    assert not hasattr(reg, "run")


def test_evaluate_tool_call() -> None:
    reg = make_registry([])
    ok = {"to": "a@example.com", "subject": "s", "body": "b"}
    assert evaluate_tool_call(reg, "read_mail", {}, 0)[0] is Decision.RUN_READ
    assert evaluate_tool_call(reg, "send_email", ok, 0)[0] is Decision.PROPOSE_WRITE
    assert evaluate_tool_call(reg, "send_email", ok, MAX_PENDING_ACTIONS)[0] is Decision.DENY
    assert evaluate_tool_call(reg, "nope", {}, 0)[0] is Decision.DENY
    assert evaluate_tool_call(reg, "send_email", "x", 0)[0] is Decision.DENY
    assert evaluate_tool_call(reg, "send_email", {"to": "x"}, 0)[0] is Decision.DENY
    assert evaluate_tool_call(reg, "read_mail", {"extra": 1}, 0)[0] is Decision.DENY


def test_canonical_payload_is_stable() -> None:
    a = canonical_payload("t", {"b": 1, "a": "é"})
    assert a == '{"args":{"a":"é","b":1},"tool":"t"}'.encode()
    assert payload_hash("t", {"a": 1, "b": 2}) == payload_hash("t", {"b": 2, "a": 1})


def test_check_approval_rejects_bad_decision_and_non_ascii_sig() -> None:
    env = make_env()
    action = env.engine.propose(
        "send_email", {"to": "a@example.com", "subject": "s", "body": "b"}, None
    )
    good = request_for(env.approval_key, action)
    assert check_approval(action, good, env.approval_key, env.clock()) is None
    bad = ApprovalRequest(action.id, "maybe", good.payload_hash, good.nonce, good.sig)
    assert check_approval(action, bad, env.approval_key, env.clock()) == "bad_decision"
    odd = ApprovalRequest(action.id, "approve", good.payload_hash, good.nonce, "é" * 64)
    assert check_approval(action, odd, env.approval_key, env.clock()) == "bad_signature"
