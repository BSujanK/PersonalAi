"""Device bearer-token authentication. Every route except /pair depends on this."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import HTTPException, Request

from agent.store.models import Device


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_device(request: Request) -> Device:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        rows = request.app.state.db.query(
            "SELECT * FROM devices WHERE token_hash = ? AND revoked = 0",
            (hash_token(token.strip()),),
        )
        if rows:
            row = rows[0]
            return Device(
                id=row["id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                revoked=False,
            )
    raise HTTPException(
        status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
    )
