"""Approval endpoints. The decision comes from the path; the signature must match it."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent.api.auth import require_device
from agent.core import policy
from agent.core.approvals import ApprovalEngine, ApprovalError
from agent.core.policy import ApprovalRequest
from agent.store.models import Device, PendingAction

router = APIRouter()


class DecisionBody(BaseModel):
    payload_hash: str = Field(max_length=128)
    nonce: str = Field(max_length=128)
    sig: str = Field(max_length=256)


def _view(action: PendingAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "tool_name": action.tool_name,
        "preview": action.preview,
        "payload_hash": action.payload_hash,
        "nonce": action.nonce,
        "status": action.status.value,
        "created_at": action.created_at.isoformat(),
        "expires_at": (action.created_at + policy.MAX_ACTION_AGE).isoformat(),
    }


@router.get("/approvals")
def list_approvals(request: Request) -> list[dict[str, Any]]:
    engine: ApprovalEngine = request.app.state.approvals
    return [_view(a) for a in engine.list_pending()]


@router.get("/approvals/{action_id}")
def get_approval(action_id: str, request: Request) -> dict[str, Any]:
    engine: ApprovalEngine = request.app.state.approvals
    action = engine.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="not_found")
    return _view(action)


def _decide(
    decision: str, action_id: str, body: DecisionBody, request: Request, device: Device
) -> dict[str, str]:
    engine: ApprovalEngine = request.app.state.approvals
    req = ApprovalRequest(action_id, decision, body.payload_hash, body.nonce, body.sig)
    try:
        action = engine.decide(req, device.id)
    except ApprovalError as err:
        if err.code == "not_found":
            status = 404
        elif err.code in ("not_pending", "expired"):
            status = 409
        else:
            status = 403
        raise HTTPException(status_code=status, detail=err.code) from None
    return {"id": action.id, "status": action.status.value}


@router.post("/approvals/{action_id}/approve")
def approve(
    action_id: str,
    body: DecisionBody,
    request: Request,
    device: Annotated[Device, Depends(require_device)],
) -> dict[str, str]:
    return _decide("approve", action_id, body, request, device)


@router.post("/approvals/{action_id}/reject")
def reject(
    action_id: str,
    body: DecisionBody,
    request: Request,
    device: Annotated[Device, Depends(require_device)],
) -> dict[str, str]:
    return _decide("reject", action_id, body, request, device)
