"""Domain records shared across the store, policy and API layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    created_at: datetime
    revoked: bool = False


@dataclass(frozen=True)
class PendingAction:
    id: str
    tool_name: str
    payload: dict[str, Any]
    preview: str
    payload_hash: str
    nonce: str
    created_at: datetime
    status: ActionStatus
    decided_at: datetime | None = None
    decided_by_device: str | None = None
    conversation_id: str | None = None
