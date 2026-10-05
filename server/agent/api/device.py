"""Phone-side endpoints: queued device commands and the push token."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent.api.auth import require_device
from agent.core.audit import AuditLog
from agent.phone.commands import AckResult, CommandError, CommandQueue
from agent.phone.push import PushNotifier
from agent.store.models import Device

router = APIRouter()


class AckBody(BaseModel):
    result: AckResult


class PushTokenBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router.get("/device/commands")
def list_commands(request: Request) -> dict[str, Any]:
    queue: CommandQueue = request.app.state.commands
    return {
        "commands": [
            {
                "id": c.id,
                "kind": c.kind,
                "params": c.params,
                "created_at": c.created_at.isoformat(),
                "expires_at": c.expires_at.isoformat(),
            }
            for c in queue.queued()
        ]
    }


@router.post("/device/commands/{command_id}/ack")
def ack_command(
    command_id: str,
    body: AckBody,
    request: Request,
    device: Annotated[Device, Depends(require_device)],
) -> dict[str, str]:
    queue: CommandQueue = request.app.state.commands
    audit: AuditLog = request.app.state.audit
    try:
        status = queue.ack(command_id, body.result, device.id)
    except CommandError as err:
        raise HTTPException(
            status_code=404 if err.code == "not_found" else 409, detail=err.code
        ) from None
    audit.record("device_command", actor=f"device:{device.id}", detail=status)
    return {"id": command_id, "status": status}


@router.put("/device/push-token")
def set_push_token(
    body: PushTokenBody, request: Request, device: Annotated[Device, Depends(require_device)]
) -> dict[str, str]:
    notifier: PushNotifier = request.app.state.push
    try:
        notifier.set_token(device.id, body.token)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid push token") from None
    return {"status": "ok"}


@router.delete("/device/push-token")
def clear_push_token(
    request: Request, device: Annotated[Device, Depends(require_device)]
) -> dict[str, str]:
    notifier: PushNotifier = request.app.state.push
    notifier.clear_token(device.id)
    return {"status": "ok"}
