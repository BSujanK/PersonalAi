"""Mail endpoints for the phone app. Feedback is a human-only path: no tool exposes it."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent.api.auth import require_device
from agent.core.audit import AuditLog
from agent.mail.digest import build_digest
from agent.mail.rules import Category
from agent.mail.services import MailServices
from agent.store.models import Device

router = APIRouter()


class FeedbackBody(BaseModel):
    account: str = Field(min_length=1, max_length=254)
    message_id: str = Field(min_length=1, max_length=128)
    category: Category


@router.get("/mail/digest")
def digest(request: Request, hours: Annotated[int, Query(ge=1, le=168)] = 24) -> dict[str, Any]:
    mail: MailServices = request.app.state.mail
    return build_digest(mail.store, request.app.state.clock(), hours).to_json()


@router.post("/mail/feedback")
def feedback(
    body: FeedbackBody, request: Request, device: Annotated[Device, Depends(require_device)]
) -> dict[str, str]:
    mail: MailServices = request.app.state.mail
    audit: AuditLog = request.app.state.audit
    message = mail.store.get(body.account, body.message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="not_found")
    # Feedback, category, sender rule and audit row commit together or not at all.
    with request.app.state.db.transaction():
        mail.store.record_feedback(body.account, body.message_id, message.category, body.category)
        mail.store.set_category(
            body.account, body.message_id, body.category, "feedback", "feedback"
        )
        mail.store.set_sender_rule(message.from_addr, body.category, "feedback")
        audit.record("mail_feedback", actor=f"device:{device.id}", detail=body.category)
    return {"status": "ok"}
