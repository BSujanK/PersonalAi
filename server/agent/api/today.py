"""GET /today: the phone's digest of important mail, upcoming deadlines and events.

The data goes only to the owner's paired phone, never to the LLM. Sources that are not
configured come back as null; a source that fails is listed in ``unavailable``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from agent.core.tools import ToolKind, ToolRegistry
from agent.mail.digest import build_digest

log = logging.getLogger(__name__)

router = APIRouter()

EVENT_DAYS = 2
DEADLINE_DAYS = 7


def _read(registry: ToolRegistry, name: str, args: dict[str, Any], failed: list[str]) -> Any:
    tool = registry.get(name)
    if tool is None or tool.kind is not ToolKind.READ:
        return None
    try:
        return tool.run(args)
    except Exception as exc:  # one broken connector must not hide the rest
        log.warning("today: %s failed: %s", name, type(exc).__name__)
        failed.append(name)
        return None


@router.get("/today")
def today(request: Request) -> dict[str, Any]:
    state = request.app.state
    registry: ToolRegistry = state.registry
    now = state.clock()
    failed: list[str] = []
    mail = getattr(state, "mail", None)
    return {
        "generated_at": now.isoformat(),
        "mail": build_digest(mail.store, now, 24).to_json() if mail is not None else None,
        "deadlines": _read(registry, "classroom_coursework", {"days": DEADLINE_DAYS}, failed),
        "events": _read(registry, "calendar_events", {"days": EVENT_DAYS, "limit": 20}, failed),
        "unavailable": failed,
    }
