"""Mail endpoints for the phone app. Feedback is a human-only path: no tool exposes it.

GET /mail/{account}/{message_id} returns one message in full for the owner's paired phone only.
Nothing here goes to the LLM, so no redaction applies: the owner sees their own mail.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from agent.api.auth import require_device
from agent.connectors.gmail import Address, MessageNotFound, parse_detail
from agent.core.audit import AuditLog
from agent.mail.digest import build_digest
from agent.mail.rules import Category
from agent.mail.services import MailServices
from agent.store.models import Device

log = logging.getLogger(__name__)

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


def _addr(a: Address) -> dict[str, str]:
    return {"name": a.name, "addr": a.addr}


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


@router.get("/mail/{account}/{message_id}")
def message_detail(
    account: Annotated[str, Path(min_length=1, max_length=254)],
    message_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
) -> dict[str, Any]:
    """The full message, fetched live from Gmail; the stored copy if Gmail cannot be reached."""
    mail: MailServices = request.app.state.mail
    stored = mail.store.get(account, message_id)
    if stored is None:  # only synced mail of configured accounts can be opened
        raise HTTPException(status_code=404, detail="not_found")
    base = {
        "account": stored.account,
        "id": stored.id,
        "thread_id": stored.thread_id,
        "category": stored.category,
        "reason": stored.reason,
    }
    try:
        detail = parse_detail(account, mail.api_for(account).get_message(message_id))
    except MessageNotFound:
        raise HTTPException(status_code=404, detail="not_found") from None
    except Exception as exc:  # offline or token trouble: fall back to the local copy
        log.warning("mail detail: live fetch failed: %s", type(exc).__name__)
        return {
            **base,
            "from": {"name": stored.from_name, "addr": stored.from_addr},
            "to": [{"name": "", "addr": a} for a in stored.to],
            "cc": [],
            "date": _iso(stored.internal_date),
            "subject": stored.subject,
            "labels": list(stored.label_ids),
            "body": stored.body,
            "body_truncated": False,
            "attachments": [],
            "source": "stored",
        }
    sender = detail.sender
    return {
        **base,
        "from": _addr(sender) if sender else {"name": "", "addr": ""},
        "to": [_addr(a) for a in detail.to],
        "cc": [_addr(a) for a in detail.cc],
        "date": _iso(detail.internal_date),
        "subject": detail.subject,
        "labels": list(detail.label_ids),
        "body": detail.body,
        "body_truncated": detail.body_truncated,
        "attachments": [
            {"name": a.name, "size": a.size, "mime": a.mime} for a in detail.attachments
        ],
        "source": "live",
    }
