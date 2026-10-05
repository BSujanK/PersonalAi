"""Device pairing. The only unauthenticated route, and only while a window is open."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent.api.auth import hash_token, new_token
from agent.core.clock import Clock
from agent.store.db import Database

router = APIRouter()

MAX_FAILED_ATTEMPTS = 5
SIGNATURE_SCHEME = "hmac-sha256:action_id|payload_hash|nonce|decision"


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def open_pairing_window(db: Database, clock: Clock, seconds: int) -> str:
    """Open a fresh one-time pairing window, closing any other. Returns the code (shown once)."""
    code = secrets.token_urlsafe(16)
    now = clock()
    with db.transaction():
        db.execute("UPDATE pairing_windows SET used = 1 WHERE used = 0")
        db.execute(
            "INSERT INTO pairing_windows (id, code_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                _hash_code(code),
                now.isoformat(),
                (now + timedelta(seconds=seconds)).isoformat(),
            ),
        )
    return code


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    device_name: str = Field(min_length=1, max_length=64)


def _unavailable() -> HTTPException:
    return HTTPException(status_code=403, detail="pairing unavailable")


@router.post("/pair")
def pair(body: PairRequest, request: Request) -> dict[str, str]:
    state = request.app.state
    db: Database = state.db
    now = state.clock()
    presented = _hash_code(body.code)
    device_id = uuid.uuid4().hex
    token = new_token()
    approval_key = secrets.token_bytes(32)
    with db.transaction():
        windows = [
            w
            for w in db.query("SELECT * FROM pairing_windows WHERE used = 0")
            if now < datetime.fromisoformat(w["expires_at"])
        ]
        match = None
        for w in windows:
            if hmac.compare_digest(w["code_hash"].encode(), presented.encode()):
                match = w
        if match is None:
            for w in windows:
                closed = w["failed_attempts"] + 1 >= MAX_FAILED_ATTEMPTS
                db.execute(
                    "UPDATE pairing_windows SET failed_attempts = failed_attempts + 1, used = ? "
                    "WHERE id = ?",
                    (1 if closed else 0, w["id"]),
                )
            failed = True
        else:
            failed = False
            db.execute("UPDATE pairing_windows SET used = 1 WHERE id = ?", (match["id"],))
            db.execute(
                "INSERT INTO devices (id, name, token_hash, created_at) VALUES (?, ?, ?, ?)",
                (device_id, body.device_name, hash_token(token), now.isoformat()),
            )
            state.keystore.set_bytes(f"approval_key:{device_id}", approval_key)
            state.audit.record("device_paired", actor="system", action_id=None, detail=device_id)
    if failed:
        raise _unavailable()
    return {
        "device_id": device_id,
        "token": token,
        "approval_key": base64.urlsafe_b64encode(approval_key).decode().rstrip("="),
        "signature_scheme": SIGNATURE_SCHEME,
    }
