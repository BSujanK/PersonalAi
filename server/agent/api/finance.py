"""Finance endpoints for the phone app. Category correction is a human-only path: no tool
exposes it. Transaction rows are returned here for the owner's own display, never to the LLM."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent.api.auth import require_device
from agent.core.audit import AuditLog
from agent.finance.categorize import Category
from agent.finance.ingest import IngestResult, SmsIn
from agent.finance.services import FinanceServices
from agent.finance.sms_parsers.common import known_senders
from agent.finance.summary import Period, format_inr, local_tz, resolve_period, spend_summary
from agent.store.models import Device
from agent.store.sync_status import SMS_INGEST, record_failure, record_ok

router = APIRouter()

MAX_SMS_BATCH = 500
MAX_FUTURE = timedelta(days=1)


class SmsItem(BaseModel):
    sender: str = Field(min_length=1, max_length=20)
    body: str = Field(min_length=1, max_length=2000)
    received_at: int  # epoch milliseconds


class SmsBatch(BaseModel):
    messages: list[SmsItem] = Field(min_length=1, max_length=MAX_SMS_BATCH)


class CategoryBody(BaseModel):
    txn_id: int
    category: Category
    remember: bool = False


def _received(item: SmsItem, latest: datetime) -> datetime:
    try:
        moment = datetime.fromtimestamp(item.received_at / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        raise HTTPException(status_code=422, detail="invalid received_at") from None
    if item.received_at < 0 or moment > latest:
        raise HTTPException(status_code=422, detail="invalid received_at")
    return moment


def _record_ingest_status(request: Request, result: IngestResult) -> None:
    """OK unless the parsers understood nothing: only unreadable bank SMS is a failure."""
    db, clock = request.app.state.db, request.app.state.clock
    understood = result.parsed + result.balances + result.duplicates + result.ignored
    if result.unparsed and not understood:
        record_failure(db, SMS_INGEST, clock, f"{result.unparsed} bank SMS could not be parsed")
    else:
        record_ok(db, SMS_INGEST, clock)


@router.post("/sms")
def ingest_sms(
    body: SmsBatch, request: Request, device: Annotated[Device, Depends(require_device)]
) -> dict[str, int]:
    finance: FinanceServices = request.app.state.finance
    audit: AuditLog = request.app.state.audit
    latest = request.app.state.clock() + MAX_FUTURE
    items = [SmsIn(m.sender, m.body, _received(m, latest)) for m in body.messages]
    with request.app.state.db.transaction():
        result = finance.ingest.ingest_sms_batch(items)
        audit.record(
            "sms_batch",
            actor=f"device:{device.id}",
            detail=(
                f"accepted={result.accepted} duplicates={result.duplicates} "
                f"parsed={result.parsed} balances={result.balances} "
                f"ignored={result.ignored} unparsed={result.unparsed}"
            ),
        )
        _record_ingest_status(request, result)
    return {
        "accepted": result.accepted,
        "duplicates": result.duplicates,
        "parsed": result.parsed,
        "balances": result.balances,
        "ignored": result.ignored,
        "unparsed": result.unparsed,
    }


@router.get("/sms/senders")
def sms_senders() -> dict[str, list[str]]:
    return {"senders": known_senders()}


@router.get("/finance/summary")
def summary(request: Request, period: Period = "this_month") -> dict[str, Any]:
    finance: FinanceServices = request.app.state.finance
    offset = request.app.state.settings.finance_utc_offset_minutes
    window = resolve_period(request.app.state.clock(), offset, period)
    txns = finance.store.txns_between(window.start, window.end)
    return {
        "from": window.first.isoformat(),
        "to": window.last.isoformat(),
        **spend_summary(txns),
    }


@router.get("/finance/balances")
def balances(request: Request) -> dict[str, Any]:
    finance: FinanceServices = request.app.state.finance
    tz = local_tz(request.app.state.settings.finance_utc_offset_minutes)
    return {
        "accounts": [
            {
                "bank": b.bank,
                "account": b.account_mask,
                "balance_inr": format_inr(b.balance_paise),
                "as_of": b.as_of.astimezone(tz).isoformat(timespec="minutes"),
                "source": b.source,
            }
            for b in finance.store.list_balances()
        ]
    }


@router.get("/finance/transactions")
def transactions(
    request: Request,
    period: Period = "this_month",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    finance: FinanceServices = request.app.state.finance
    offset = request.app.state.settings.finance_utc_offset_minutes
    window = resolve_period(request.app.state.clock(), offset, period)
    txns = finance.store.txns_between(window.start, window.end)
    newest = sorted(txns, key=lambda t: (t.occurred_at, t.id), reverse=True)[:limit]
    tz = local_tz(offset)
    return {
        "total": len(txns),
        "transactions": [
            {
                "id": t.id,
                "date": t.occurred_at.astimezone(tz).date().isoformat(),
                "direction": t.direction,
                "amount_inr": format_inr(t.amount_paise),
                "counterparty": t.counterparty,
                "account": t.account_mask,
                "category": t.category,
                "sources": [s for s, on in (("sms", t.from_sms), ("email", t.from_email)) if on],
            }
            for t in newest
        ],
    }


@router.post("/finance/category")
def set_category(
    body: CategoryBody, request: Request, device: Annotated[Device, Depends(require_device)]
) -> dict[str, str]:
    finance: FinanceServices = request.app.state.finance
    audit: AuditLog = request.app.state.audit
    txn = finance.store.get_txn(body.txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="not_found")
    remember = body.remember and txn.counterparty is not None
    # Category, owner rule and audit row commit together or not at all.
    with request.app.state.db.transaction():
        finance.store.set_category(body.txn_id, body.category, "user")
        if remember and txn.counterparty is not None:
            finance.store.set_category_rule(txn.counterparty, body.category)
        audit.record(
            "finance_category",
            actor=f"device:{device.id}",
            detail=f"{body.category} remember={remember}",
        )
    return {"status": "ok"}
