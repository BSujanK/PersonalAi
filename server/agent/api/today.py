"""GET /today: the phone's digest of important mail, upcoming deadlines and events.

The data goes only to the owner's paired phone, never to the LLM. Sources that are not
configured come back as null; a source that fails is listed in ``unavailable``."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from agent.core.tools import ToolKind, ToolRegistry
from agent.mail.digest import build_digest

log = logging.getLogger(__name__)

router = APIRouter()

EVENT_DAYS = 2
DEADLINE_DAYS = 7
SECTIONS = ("mail", "events", "deadlines")


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


def _requested(sections: str | None) -> frozenset[str]:
    """The sections asked for: every one without the parameter, else the named subset."""
    if sections is None:
        return frozenset(SECTIONS)
    names = sections.split(",")
    if any(name not in SECTIONS for name in names):
        raise HTTPException(status_code=422, detail="invalid_sections")
    return frozenset(names)


@router.get("/today")
def today(
    request: Request, sections: Annotated[str | None, Query(max_length=64)] = None
) -> dict[str, Any]:
    """The digest. ``sections`` (comma-separated ``mail``, ``events``, ``deadlines``) limits it:
    sections not named are left out of the response and their connector is not called."""
    wanted = _requested(sections)
    state = request.app.state
    registry: ToolRegistry = state.registry
    now = state.clock()
    failed: list[str] = []
    out: dict[str, Any] = {"generated_at": now.isoformat()}
    if "mail" in wanted:
        mail = getattr(state, "mail", None)
        out["mail"] = build_digest(mail.store, now, 24).to_json() if mail is not None else None
    if "deadlines" in wanted:
        out["deadlines"] = _read(registry, "classroom_coursework", {"days": DEADLINE_DAYS}, failed)
    if "events" in wanted:
        out["events"] = _read(
            registry, "calendar_events", {"days": EVENT_DAYS, "limit": 20}, failed
        )
    out["unavailable"] = failed
    return out
