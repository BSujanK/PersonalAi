"""Alerts, alert settings and deadlines for the phone.

The content goes only to the owner's paired phone over Tailscale; push notifications stay
content-free. ``POST /deadlines/{id}/undo`` can only remove a calendar event the agent added
automatically (see ``agent.proactive.autocal``)."""

from __future__ import annotations

import base64
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from agent.api.auth import require_device
from agent.config import Settings, account_label
from agent.core.audit import AuditLog
from agent.proactive.alerts import Alert, AlertSettings
from agent.proactive.deadlines import DeadlineStore, deadline_target
from agent.proactive.services import ProactiveServices
from agent.store.models import Device

router = APIRouter()


class AlertSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    important_mail: StrictBool
    deadlines: StrictBool
    briefing: StrictBool
    briefing_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def _services(request: Request) -> ProactiveServices:
    services: ProactiveServices = request.app.state.proactive
    return services


def _enriched_target(target: dict[str, Any], deadlines: DeadlineStore) -> dict[str, Any]:
    """The stored target, completed for alerts raised before targets carried their source: a
    deadline target gains its source fields, a mail target gets ``id`` from ``message_id``."""
    out = dict(target)
    if out.get("type") == "deadline" and "source" not in out:
        deadline_id = out.get("deadline_id")
        found = deadlines.get(deadline_id) if isinstance(deadline_id, int) else None
        if found is not None:
            out.update(deadline_target(found))
    elif out.get("type") == "mail" and "id" not in out and "message_id" in out:
        out["id"] = out["message_id"]
    return out


def _target_account(target: dict[str, Any]) -> str | None:
    account = target.get("account")
    if not isinstance(account, str):
        source = target.get("source")
        account = source.get("account") if isinstance(source, dict) else None
    return account if isinstance(account, str) and account else None


def _alert_json(alert: Alert, deadlines: DeadlineStore, settings: Settings) -> dict[str, Any]:
    target = _enriched_target(alert.target, deadlines)
    item: dict[str, Any] = {
        "id": alert.id,
        "kind": alert.kind,
        "title": alert.title,
        "body": alert.body,
        "created_at": alert.created_at,
        "target": target,
    }
    account = _target_account(target)
    if account is not None:
        item["source_account"] = account
        item["source_label"] = account_label(settings, account)
    if alert.actions:
        item["actions"] = list(alert.actions)
    return item


def _settings_json(settings: AlertSettings) -> dict[str, Any]:
    return {
        "important_mail": settings.important_mail,
        "deadlines": settings.deadlines,
        "briefing": settings.briefing,
        "briefing_time": settings.briefing_time,
    }


@router.get("/notifications")
def notifications(
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    services = _services(request)
    alerts = services.alerts
    settings: Settings = request.app.state.settings
    return {
        "items": [
            _alert_json(a, services.deadlines.store, settings) for a in alerts.since(after, limit)
        ],
        "latest_id": alerts.latest_id(),
    }


@router.get("/notifications/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return _settings_json(_services(request).alerts.settings())


@router.put("/notifications/settings")
def put_settings(
    body: AlertSettingsBody, request: Request, device: Annotated[Device, Depends(require_device)]
) -> dict[str, Any]:
    saved = _services(request).alerts.save_settings(
        AlertSettings(body.important_mail, body.deadlines, body.briefing, body.briefing_time)
    )
    audit: AuditLog = request.app.state.audit
    audit.record("alert_settings", actor=f"device:{device.id}")
    return _settings_json(saved)


@router.get("/deadlines")
def deadlines(request: Request, days: Annotated[int, Query(ge=1, le=60)] = 14) -> dict[str, Any]:
    """Deadlines due within ``days``, soonest first. Ones whose calendar entry was undone stay
    listed (status ``undone``): the deadline is real, only the calendar entry was removed."""
    services = _services(request)
    store = services.deadlines.store
    found = store.upcoming(days, services.offset_minutes, statuses=("active", "undone"))
    on_calendar = store.calendar_added_ids([d.id for d in found])
    return {
        "items": [
            {
                "id": d.id,
                "kind": d.kind,
                "title": d.title,
                "due": d.due.isoformat(),
                "source": d.source,
                "source_account": d.source_account,
                "source_id": d.source_id,
                "calendar_added": d.id in on_calendar,
                "status": d.status,
            }
            for d in found
        ]
    }


def _calendar_link(account: str, event_id: str) -> str:
    eid = base64.urlsafe_b64encode(f"{event_id} {account}".encode()).decode().rstrip("=")
    return f"https://www.google.com/calendar/event?eid={eid}"


@router.get("/deadlines/{deadline_id}")
def deadline_detail(
    deadline_id: Annotated[int, Path(ge=1, le=2**62)], request: Request
) -> dict[str, Any]:
    """One deadline: ids, labels and the title, never mail or post text. ``calendar`` is set
    only while the agent's auto-added event is live."""
    store = _services(request).deadlines.store
    found = store.get(deadline_id)
    if found is None:
        raise HTTPException(status_code=404, detail="not_found")
    settings: Settings = request.app.state.settings
    event = store.calendar_event(deadline_id)
    item: dict[str, Any] = {
        "id": found.id,
        "kind": found.kind,
        "title": found.title,
        "due": found.due.isoformat(),
        "source": found.source,
        "source_account": found.source_account,
        "source_label": account_label(settings, found.source_account),
        "source_id": found.source_id,
        "status": found.status,
        "calendar_added": event is not None,
    }
    ids = deadline_target(found)
    for key in ("message_id", "course_id"):
        if key in ids:
            item[key] = ids[key]
    item["calendar"] = (
        {"account": event[0], "event_id": event[1], "link": _calendar_link(event[0], event[1])}
        if event is not None
        else None
    )
    return item


@router.post("/deadlines/{deadline_id}/undo")
def undo(
    deadline_id: Annotated[int, Path(ge=1, le=2**62)],
    request: Request,
    device: Annotated[Device, Depends(require_device)],
) -> dict[str, str]:
    outcome = _services(request).autocal.undo(deadline_id, device.id)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="not_found")
    if outcome == "refused":
        raise HTTPException(status_code=409, detail="refused")
    return {"status": "undone"}
