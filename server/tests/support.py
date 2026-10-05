"""Shared test helpers: fake clock, fake tools and a fully wired approval environment."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from agent.core.approvals import ApprovalEngine
from agent.core.audit import AuditLog
from agent.core.policy import ApprovalRequest, expected_signature, signature_message
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.store.models import PendingAction

START = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
DEVICE_ID = "dev1"


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


SEND_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["to", "subject", "body"],
    "additionalProperties": False,
}


@dataclass
class Env:
    db: Database
    cipher: FieldCipher
    registry: ToolRegistry
    audit: AuditLog
    keystore: KeyStore
    clock: FakeClock
    engine: ApprovalEngine
    approval_key: bytes
    executed: list[dict[str, Any]] = field(default_factory=list)


def make_registry(executed: list[dict[str, Any]], mail_body: str = "hello") -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="send_email",
            description="Send an email (requires approval).",
            parameters=SEND_PARAMS,
            kind=ToolKind.WRITE,
            run=lambda args: executed.append(args) or {"sent": True},
            preview=lambda args: f"Send '{args['subject']}' to {args['to']}",
        )
    )
    registry.register(
        Tool(
            name="read_mail",
            description="Read the latest mail.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            kind=ToolKind.READ,
            run=lambda _args: {"from": "sender@example.com", "body": mail_body},
        )
    )
    return registry


def make_env(mail_body: str = "hello") -> Env:
    db = Database(":memory:")
    clock = FakeClock()
    cipher = FieldCipher(bytes(range(32)))
    keystore = KeyStore()
    key = bytes(range(100, 132))
    keystore.set_bytes(f"approval_key:{DEVICE_ID}", key)
    executed: list[dict[str, Any]] = []
    registry = make_registry(executed, mail_body)
    audit = AuditLog(db, clock)
    engine = ApprovalEngine(db, cipher, registry, audit, keystore, clock)
    return Env(db, cipher, registry, audit, keystore, clock, engine, key, executed)


def sign(key: bytes, action: PendingAction, decision: str) -> str:
    msg = signature_message(action.id, action.payload_hash, action.nonce, decision)
    return expected_signature(key, msg)


def request_for(key: bytes, action: PendingAction, decision: str = "approve") -> ApprovalRequest:
    return ApprovalRequest(
        action.id, decision, action.payload_hash, action.nonce, sign(key, action, decision)
    )


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")
