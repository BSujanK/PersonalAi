"""Paired-device management on the laptop: list and revoke (SECURITY.md, device revocation)."""

from __future__ import annotations

from typing import Any

from agent.core.audit import AuditLog
from agent.store.db import Database
from agent.store.keystore import KeyStore


def list_devices(db: Database) -> list[dict[str, Any]]:
    """Every paired device, oldest first. Holds no secrets (tokens are stored only as hashes)."""
    rows = db.query("SELECT id, name, created_at, revoked FROM devices ORDER BY created_at, id")
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "created_at": r["created_at"],
            "revoked": bool(r["revoked"]),
        }
        for r in rows
    ]


def revoke_devices(
    db: Database, keystore: KeyStore, audit: AuditLog, device_ids: list[str]
) -> list[str]:
    """Revoke the given active devices and delete their keyring secrets. Returns those revoked.

    A revoked token fails ``require_device``, and without its approval key the device can never
    approve again, even if the row were restored.
    """
    revoked: list[str] = []
    with db.transaction():
        for device_id in device_ids:
            cur = db.execute(
                "UPDATE devices SET revoked = 1 WHERE id = ? AND revoked = 0", (device_id,)
            )
            if cur.rowcount == 1:
                revoked.append(device_id)
                audit.record("device_revoked", actor="owner", action_id=None, detail=device_id)
    for device_id in revoked:
        keystore.delete(f"approval_key:{device_id}")
        keystore.delete(f"push_token:{device_id}")
    return revoked
