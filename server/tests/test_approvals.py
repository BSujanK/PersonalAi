from __future__ import annotations

import json
import threading
from datetime import timedelta
from typing import Any

import pytest

from agent.core.approvals import ApprovalError
from agent.core.policy import ApprovalRequest, expected_signature, signature_message
from agent.store.models import ActionStatus, PendingAction
from tests.support import DEVICE_ID, Env, make_env, request_for, sign

ARGS = {"to": "friend@example.com", "subject": "Hi", "body": "Lunch?"}


def _propose(env: Env) -> PendingAction:
    return env.engine.propose("send_email", ARGS, "conv1")


def _denied_audit_rows(env: Env) -> list[str]:
    rows = env.db.query("SELECT detail FROM audit_log WHERE event = 'approval_denied' ORDER BY seq")
    return [r["detail"] for r in rows]


def _assert_denied(env: Env, req: ApprovalRequest, code: str) -> None:
    with pytest.raises(ApprovalError) as err:
        env.engine.decide(req, DEVICE_ID)
    assert err.value.code == code
    assert env.executed == []
    assert code in _denied_audit_rows(env)


def test_propose_creates_pending_without_executing() -> None:
    env = make_env()
    action = _propose(env)
    assert action.status is ActionStatus.PENDING
    assert action.payload == ARGS
    assert "friend@example.com" in action.preview
    assert env.executed == []
    row = env.db.query("SELECT * FROM pending_actions")[0]
    assert b"friend@example.com" not in row["payload_enc"]
    assert b"friend@example.com" not in row["preview_enc"]
    assert env.audit.verify()


def test_propose_rejects_read_and_unknown_tools() -> None:
    env = make_env()
    for name in ("read_mail", "nope"):
        with pytest.raises(ValueError, match="WRITE"):
            env.engine.propose(name, {}, None)


def test_approve_executes_exactly_once_with_stored_payload() -> None:
    env = make_env()
    action = _propose(env)
    done = env.engine.decide(request_for(env.approval_key, action), DEVICE_ID)
    assert done.status is ActionStatus.EXECUTED
    assert done.decided_by_device == DEVICE_ID
    assert env.executed == [ARGS]
    assert env.audit.verify()
    events = [r["event"] for r in env.db.query("SELECT event FROM audit_log ORDER BY seq")]
    assert events == ["proposed", "approved", "executed"]
    result_enc = env.db.query("SELECT result_enc FROM pending_actions")[0]["result_enc"]
    assert json.loads(
        env.cipher.decrypt_str(result_enc, f"pending_actions.result:{action.id}")
    ) == {"sent": True}


def test_reject_with_valid_sig_never_executes() -> None:
    env = make_env()
    action = _propose(env)
    done = env.engine.decide(request_for(env.approval_key, action, "reject"), DEVICE_ID)
    assert done.status is ActionStatus.REJECTED
    assert env.executed == []


@pytest.mark.parametrize("sig", ["", "0" * 64, "zz", "a" * 63])
def test_missing_or_garbage_sig(sig: str) -> None:
    env = make_env()
    action = _propose(env)
    req = ApprovalRequest(action.id, "approve", action.payload_hash, action.nonce, sig)
    _assert_denied(env, req, "bad_signature")


def test_sig_with_wrong_key() -> None:
    env = make_env()
    action = _propose(env)
    req = request_for(bytes(32), action)
    _assert_denied(env, req, "bad_signature")


def test_reject_sig_cannot_approve() -> None:
    env = make_env()
    action = _propose(env)
    req = ApprovalRequest(
        action.id,
        "approve",
        action.payload_hash,
        action.nonce,
        sign(env.approval_key, action, "reject"),
    )
    _assert_denied(env, req, "bad_signature")


def test_sig_over_different_payload_hash() -> None:
    env = make_env()
    action = _propose(env)
    msg = signature_message(action.id, "f" * 64, action.nonce, "approve")
    req = ApprovalRequest(
        action.id, "approve", action.payload_hash, action.nonce,
        expected_signature(env.approval_key, msg),
    )  # fmt: skip
    _assert_denied(env, req, "bad_signature")


def test_changed_payload_hash_in_request() -> None:
    env = make_env()
    action = _propose(env)
    good = request_for(env.approval_key, action)
    req = ApprovalRequest(action.id, "approve", "f" * 64, good.nonce, good.sig)
    _assert_denied(env, req, "hash_mismatch")


def test_wrong_nonce() -> None:
    env = make_env()
    action = _propose(env)
    good = request_for(env.approval_key, action)
    req = ApprovalRequest(action.id, "approve", good.payload_hash, "other", good.sig)
    _assert_denied(env, req, "nonce_mismatch")


def test_tampered_stored_payload_is_detected() -> None:
    env = make_env()
    action = _propose(env)
    forged = dict(ARGS, to="attacker@example.com")
    env.db.execute(
        "UPDATE pending_actions SET payload_enc = ? WHERE id = ?",
        (
            env.cipher.encrypt(json.dumps(forged), f"pending_actions.payload:{action.id}"),
            action.id,
        ),
    )
    _assert_denied(env, request_for(env.approval_key, action), "integrity")


def test_undecryptable_stored_payload_is_integrity_failure() -> None:
    env = make_env()
    action = _propose(env)
    env.db.execute("UPDATE pending_actions SET payload_enc = x'0102' WHERE id = ?", (action.id,))
    _assert_denied(env, request_for(env.approval_key, action), "integrity")


def test_replay_after_approval() -> None:
    env = make_env()
    action = _propose(env)
    req = request_for(env.approval_key, action)
    env.engine.decide(req, DEVICE_ID)
    with pytest.raises(ApprovalError) as err:
        env.engine.decide(req, DEVICE_ID)
    assert err.value.code == "not_pending"
    assert env.executed == [ARGS]


def test_expired_after_fifteen_minutes() -> None:
    env = make_env()
    action = _propose(env)
    req = request_for(env.approval_key, action)
    env.clock.advance(timedelta(minutes=15, seconds=1))
    _assert_denied(env, req, "expired")
    fresh = env.engine.get(action.id)
    assert fresh is not None and fresh.status is ActionStatus.EXPIRED
    assert [r["event"] for r in env.db.query("SELECT event FROM audit_log")][-2:] == [
        "approval_denied",
        "expired",
    ]


def test_exactly_fifteen_minutes_is_still_valid() -> None:
    env = make_env()
    action = _propose(env)
    env.clock.advance(timedelta(minutes=15))
    assert env.engine.decide(request_for(env.approval_key, action), DEVICE_ID).status is (
        ActionStatus.EXECUTED
    )


def test_future_dated_action_is_clock_skew() -> None:
    env = make_env()
    env.clock.advance(timedelta(minutes=5))
    action = _propose(env)
    req = request_for(env.approval_key, action)
    env.clock.advance(timedelta(minutes=-5))
    _assert_denied(env, req, "clock_skew")


def test_device_without_approval_key_cannot_approve() -> None:
    env = make_env()
    action = _propose(env)
    req = request_for(env.approval_key, action)
    with pytest.raises(ApprovalError) as err:
        env.engine.decide(req, "token-only-device")
    assert err.value.code == "bad_signature"
    assert env.executed == []
    assert "bad_signature" in _denied_audit_rows(env)


def test_uppercase_hex_sig_is_rejected() -> None:
    env = make_env()
    action = _propose(env)
    good = request_for(env.approval_key, action)
    req = ApprovalRequest(action.id, "approve", good.payload_hash, good.nonce, good.sig.upper())
    _assert_denied(env, req, "bad_signature")


def test_unknown_action_is_not_found_and_audited() -> None:
    env = make_env()
    req = ApprovalRequest("nope", "approve", "a", "b", "c")
    _assert_denied(env, req, "not_found")


def test_unknown_decision_is_rejected() -> None:
    env = make_env()
    action = _propose(env)
    good = request_for(env.approval_key, action)
    req = ApprovalRequest(action.id, "execute", good.payload_hash, good.nonce, good.sig)
    _assert_denied(env, req, "bad_decision")


def test_denied_approval_leaves_audit_row_and_keeps_pending() -> None:
    env = make_env()
    action = _propose(env)
    req = ApprovalRequest(action.id, "approve", action.payload_hash, action.nonce, "0" * 64)
    with pytest.raises(ApprovalError):
        env.engine.decide(req, DEVICE_ID)
    row = env.db.query("SELECT * FROM audit_log WHERE event = 'approval_denied'")[0]
    assert row["action_id"] == action.id
    assert row["actor"] == f"device:{DEVICE_ID}"
    assert row["detail"] == "bad_signature"
    assert env.engine.get(action.id).status is ActionStatus.PENDING  # type: ignore[union-attr]
    assert env.audit.verify()


def test_executor_failure_marks_failed_without_leaking_message() -> None:
    env = make_env()

    def boom(_args: dict[str, Any]) -> None:
        raise RuntimeError("secret detail 4111111111111111")

    from agent.core.tools import Tool, ToolKind

    env.registry.register(
        Tool("boom_tool", "d", {"type": "object"}, ToolKind.WRITE, boom, preview=lambda a: "p")
    )
    action = env.engine.propose("boom_tool", {}, None)
    done = env.engine.decide(request_for(env.approval_key, action), DEVICE_ID)
    assert done.status is ActionStatus.FAILED
    detail = env.db.query("SELECT detail FROM audit_log WHERE event = 'execution_failed'")[0][
        "detail"
    ]
    assert detail == "RuntimeError"


def test_concurrent_double_approve_executes_once() -> None:
    env = make_env()
    action = _propose(env)
    req = request_for(env.approval_key, action)
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait()
        try:
            env.engine.decide(req, DEVICE_ID)
            outcomes.append("ok")
        except ApprovalError as err:
            outcomes.append(err.code)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["not_pending", "ok"]
    assert env.executed == [ARGS]


def test_list_pending_expires_old_actions() -> None:
    env = make_env()
    old = _propose(env)
    env.clock.advance(timedelta(minutes=16))
    fresh = _propose(env)
    assert [a.id for a in env.engine.list_pending()] == [fresh.id]
    assert env.engine.pending_count() == 1
    stale = env.engine.get(old.id)
    assert stale is not None and stale.status is ActionStatus.EXPIRED
