"""Approval engine: the only place a WRITE tool executor is ever invoked (CLAUDE.md rule 1)."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agent.core import policy
from agent.core.audit import AuditLog
from agent.core.clock import Clock
from agent.core.policy import ApprovalRequest
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.store.crypto import DecryptionError, FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.store.models import ActionStatus, PendingAction

log = logging.getLogger(__name__)


class ApprovalError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ApprovalEngine:
    def __init__(
        self,
        db: Database,
        cipher: FieldCipher,
        registry: ToolRegistry,
        audit: AuditLog,
        keystore: KeyStore,
        clock: Clock,
        *,
        on_proposed: Callable[[], None] | None = None,
    ) -> None:
        self._db = db
        self._cipher = cipher
        self._registry = registry
        self._audit = audit
        self._keystore = keystore
        self._clock = clock
        self._on_proposed = on_proposed

    def _to_action(self, row: sqlite3.Row) -> PendingAction:
        aid = row["id"]
        payload = json.loads(
            self._cipher.decrypt_str(row["payload_enc"], f"pending_actions.payload:{aid}")
        )
        preview = self._cipher.decrypt_str(row["preview_enc"], f"pending_actions.preview:{aid}")
        decided = row["decided_at"]
        return PendingAction(
            id=aid,
            tool_name=row["tool_name"],
            payload=payload,
            preview=preview,
            payload_hash=row["payload_hash"],
            nonce=row["nonce"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=ActionStatus(row["status"]),
            decided_at=datetime.fromisoformat(decided) if decided else None,
            decided_by_device=row["decided_by_device"],
            conversation_id=row["conversation_id"],
        )

    def propose(
        self, tool_name: str, args: dict[str, Any], conversation_id: str | None
    ) -> PendingAction:
        tool: Tool | None = self._registry.get(tool_name)
        if tool is None or tool.kind is not ToolKind.WRITE or tool.preview is None:
            raise ValueError("only registered WRITE tools can be proposed")
        action_id = uuid.uuid4().hex
        preview = tool.preview(args)
        now = self._clock()
        with self._db.transaction():
            self._db.execute(
                "INSERT INTO pending_actions (id, tool_name, payload_enc, preview_enc, "
                "payload_hash, nonce, created_at, status, conversation_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    action_id,
                    tool_name,
                    self._cipher.encrypt(
                        json.dumps(args, ensure_ascii=False), f"pending_actions.payload:{action_id}"
                    ),
                    self._cipher.encrypt(preview, f"pending_actions.preview:{action_id}"),
                    policy.payload_hash(tool_name, args),
                    secrets.token_urlsafe(32),
                    now.isoformat(),
                    conversation_id,
                ),
            )
            self._audit.record("proposed", actor="agent", action_id=action_id, detail=tool_name)
        action = self._require(action_id)
        if self._on_proposed is not None:
            try:
                self._on_proposed()
            except Exception as exc:  # a notification failure must not undo the proposal
                log.warning("proposal listener failed: %s", type(exc).__name__)
        return action

    def _require(self, action_id: str) -> PendingAction:
        action = self.get(action_id)
        if action is None:
            raise ApprovalError("not_found")
        return action

    def get(self, action_id: str) -> PendingAction | None:
        rows = self._db.query("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        return self._to_action(rows[0]) if rows else None

    def _expire_stale(self) -> None:
        cutoff = (self._clock() - policy.MAX_ACTION_AGE).isoformat()
        with self._db.transaction():
            stale = self._db.query(
                "SELECT id FROM pending_actions WHERE status = 'pending' AND created_at < ?",
                (cutoff,),
            )
            for row in stale:
                self._db.execute(
                    "UPDATE pending_actions SET status = 'expired' WHERE id = ? "
                    "AND status = 'pending'",
                    (row["id"],),
                )
                self._audit.record("expired", actor="system", action_id=row["id"])

    def list_pending(self) -> list[PendingAction]:
        self._expire_stale()
        rows = self._db.query(
            "SELECT * FROM pending_actions WHERE status = 'pending' ORDER BY created_at"
        )
        return [self._to_action(r) for r in rows]

    def pending_count(self) -> int:
        self._expire_stale()
        return int(
            self._db.query("SELECT COUNT(*) AS n FROM pending_actions WHERE status = 'pending'")[0][
                "n"
            ]
        )

    def decide(self, req: ApprovalRequest, device_id: str) -> PendingAction:
        actor = f"device:{device_id}"
        failure: str | None = None
        action: PendingAction | None = None
        # The check, its audit row and any expiry commit together, before an error is raised.
        with self._db.transaction():
            rows = self._db.query("SELECT * FROM pending_actions WHERE id = ?", (req.action_id,))
            key = self._keystore.get_bytes(f"approval_key:{device_id}")
            if not rows:
                failure = "not_found"
            elif key is None:
                failure = "bad_signature"
            else:
                try:
                    action = self._to_action(rows[0])
                except (DecryptionError, ValueError):
                    failure = "integrity"
                else:
                    failure = policy.check_approval(action, req, key, self._clock())
            if failure is None and action is not None:
                status = (
                    ActionStatus.APPROVED if req.decision == "approve" else ActionStatus.REJECTED
                )
                cur = self._db.execute(
                    "UPDATE pending_actions SET status = ?, decided_at = ?, decided_by_device = ? "
                    "WHERE id = ? AND status = 'pending' AND nonce = ?",
                    (status.value, self._clock().isoformat(), device_id, action.id, action.nonce),
                )
                if cur.rowcount != 1:
                    failure = "not_pending"
                else:
                    self._audit.record(
                        status.value, actor=actor, action_id=action.id, detail=req.decision
                    )
            if failure is not None:
                self._audit.record(
                    "approval_denied", actor=actor, action_id=req.action_id, detail=failure
                )
                if failure == "expired":
                    self._db.execute(
                        "UPDATE pending_actions SET status = 'expired' WHERE id = ? "
                        "AND status = 'pending'",
                        (req.action_id,),
                    )
                    self._audit.record("expired", actor="system", action_id=req.action_id)
        if failure is not None:
            raise ApprovalError(failure)
        assert action is not None  # noqa: S101 - failure is None implies a loaded action
        if req.decision == "approve":
            self._execute(action)
        return self._require(action.id)

    def _execute(self, action: PendingAction) -> None:
        """Run the executor with the stored payload, outside any lock or transaction."""
        executor = self._registry.executor_for_approved(action.tool_name)
        try:
            result = executor(action.payload)
            outcome = ActionStatus.EXECUTED
            result_enc = self._cipher.encrypt(
                json.dumps(result, default=str), f"pending_actions.result:{action.id}"
            )
            detail = ""
        except Exception as exc:  # executor failures must not escape; record type only
            outcome = ActionStatus.FAILED
            result_enc = None
            detail = type(exc).__name__
            log.warning("action execution failed: %s", detail)
        with self._db.transaction():
            self._db.execute(
                "UPDATE pending_actions SET status = ?, result_enc = ? WHERE id = ?",
                (outcome.value, result_enc, action.id),
            )
            self._audit.record(
                "executed" if outcome is ActionStatus.EXECUTED else "execution_failed",
                actor="system",
                action_id=action.id,
                detail=detail,
            )
