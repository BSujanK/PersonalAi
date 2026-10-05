"""Pure approval and tool-call decisions (CLAUDE.md rules 1 and 2). No I/O."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from agent.store.models import ActionStatus, PendingAction

if TYPE_CHECKING:
    from agent.core.tools import ToolRegistry

MAX_ACTION_AGE = timedelta(minutes=15)
CLOCK_SKEW = timedelta(seconds=30)
MAX_PENDING_ACTIONS = 25

# Rule 2: no broker order/modify/cancel tools, whatever they are called.
_BROKER = r"(?:groww|broker|demat|stock|trade)"
_VERB = r"(?:order|buy|sell|modify|cancel|place)"
FORBIDDEN_TOOL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"{_BROKER}.*{_VERB}", re.IGNORECASE),
    re.compile(rf"{_VERB}.*{_BROKER}", re.IGNORECASE),
)

_SIG_RE = re.compile(r"[0-9a-f]{64}")
_DECISIONS = frozenset({"approve", "reject"})


class Decision(StrEnum):
    RUN_READ = "run_read"
    PROPOSE_WRITE = "propose_write"
    DENY = "deny"


def evaluate_tool_call(
    registry: ToolRegistry, name: str, args: Any, pending_count: int
) -> tuple[Decision, str]:
    tool = registry.get(name)
    if tool is None:
        return Decision.DENY, "unknown tool"
    if not isinstance(args, dict):
        return Decision.DENY, "arguments must be an object"
    missing = [k for k in tool.parameters.get("required", []) if k not in args]
    if missing:
        return Decision.DENY, "missing required arguments"
    if tool.parameters.get("additionalProperties") is False:
        allowed = set(tool.parameters.get("properties", {}))
        if any(k not in allowed for k in args):
            return Decision.DENY, "unexpected arguments"
    # StrEnum compares equal to its value; avoids importing tools at runtime (import cycle).
    if tool.kind == "read":
        return Decision.RUN_READ, "read tool"
    if pending_count >= MAX_PENDING_ACTIONS:
        return Decision.DENY, "too many pending approvals"
    return Decision.PROPOSE_WRITE, "write tool requires approval"


def canonical_payload(tool_name: str, args: dict[str, Any]) -> bytes:
    return json.dumps(
        {"tool": tool_name, "args": args},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def payload_hash(tool_name: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(tool_name, args)).hexdigest()


def signature_message(action_id: str, payload_hash: str, nonce: str, decision: str) -> bytes:
    return f"{action_id}|{payload_hash}|{nonce}|{decision}".encode()


def expected_signature(approval_key: bytes, msg: bytes) -> str:
    return hmac.new(approval_key, msg, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ApprovalRequest:
    action_id: str
    decision: str
    payload_hash: str
    nonce: str
    sig: str


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def check_approval(
    action: PendingAction, req: ApprovalRequest, approval_key: bytes, now: datetime
) -> str | None:
    """Return None if the request may proceed, else a short reason code."""
    if req.decision not in _DECISIONS:
        return "bad_decision"
    if action.status != ActionStatus.PENDING:
        return "not_pending"
    if now - action.created_at > MAX_ACTION_AGE:
        return "expired"
    if action.created_at - now > CLOCK_SKEW:
        return "clock_skew"
    if not _same(payload_hash(action.tool_name, action.payload), action.payload_hash):
        return "integrity"
    if not _same(req.payload_hash, action.payload_hash):
        return "hash_mismatch"
    if not _same(req.nonce, action.nonce):
        return "nonce_mismatch"
    if not _SIG_RE.fullmatch(req.sig):
        return "bad_signature"
    msg = signature_message(action.id, action.payload_hash, action.nonce, req.decision)
    if not _same(req.sig, expected_signature(approval_key, msg)):
        return "bad_signature"
    return None
