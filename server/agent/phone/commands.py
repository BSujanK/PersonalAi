"""Queue of device commands. Only an approved WRITE executor ever enqueues one."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from agent.core.clock import Clock
from agent.store.crypto import FieldCipher
from agent.store.db import Database

CommandKind = Literal["set_alarm", "set_timer", "reminder"]
AckResult = Literal["done", "failed"]


@dataclass(frozen=True)
class DeviceCommand:
    id: str
    kind: CommandKind
    params: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    status: str


class CommandError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CommandQueue:
    def __init__(self, db: Database, cipher: FieldCipher, clock: Clock) -> None:
        self._db = db
        self._cipher = cipher
        self._clock = clock

    def enqueue(self, kind: CommandKind, params: dict[str, Any], expires_at: datetime) -> str:
        command_id = uuid.uuid4().hex
        with self._db.transaction():
            self._db.execute(
                "INSERT INTO device_commands (id, kind, params_enc, created_at, expires_at, "
                "status) VALUES (?, ?, ?, ?, ?, 'queued')",
                (
                    command_id,
                    kind,
                    self._cipher.encrypt(
                        json.dumps(params, ensure_ascii=False),
                        f"device_commands.params:{command_id}",
                    ),
                    self._clock().isoformat(),
                    expires_at.astimezone(UTC).isoformat(),
                ),
            )
        return command_id

    def _expire_stale(self) -> None:
        self._db.execute(
            "UPDATE device_commands SET status = 'expired' "
            "WHERE status = 'queued' AND expires_at <= ?",
            (self._clock().astimezone(UTC).isoformat(),),
        )

    def queued(self) -> list[DeviceCommand]:
        with self._db.transaction():
            self._expire_stale()
            rows = self._db.query(
                "SELECT * FROM device_commands WHERE status = 'queued' ORDER BY created_at"
            )
        return [
            DeviceCommand(
                id=r["id"],
                kind=r["kind"],
                params=json.loads(
                    self._cipher.decrypt_str(r["params_enc"], f"device_commands.params:{r['id']}")
                ),
                created_at=datetime.fromisoformat(r["created_at"]),
                expires_at=datetime.fromisoformat(r["expires_at"]),
                status=r["status"],
            )
            for r in rows
        ]

    def ack(self, command_id: str, result: AckResult, device_id: str) -> str:
        """Mark a queued command done or failed. Each command is acknowledged once."""
        with self._db.transaction():
            rows = self._db.query("SELECT status FROM device_commands WHERE id = ?", (command_id,))
            if not rows:
                raise CommandError("not_found")
            cur = self._db.execute(
                "UPDATE device_commands SET status = ?, acked_at = ?, acked_by_device = ? "
                "WHERE id = ? AND status = 'queued'",
                (result, self._clock().isoformat(), device_id, command_id),
            )
            if cur.rowcount != 1:
                raise CommandError("not_queued")
        return result
