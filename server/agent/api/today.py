"""GET /today: the phone's digest of important mail, upcoming deadlines and events.

The data goes only to the owner's paired phone, never to the LLM. The request reads only the
cache that a background job fills (``TodayCache``), so it never waits on Google. ``sections``
limits the response to the named parts. A source that is not configured comes back as null; one
with nothing cached yet is null and listed in ``unavailable``; one whose data is old or whose last
refresh failed is listed in ``stale``."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from agent.api.today_cache import SOURCES, TodayCache

router = APIRouter()

STALE_AFTER_REFRESHES = 3


def _requested(sections: str | None) -> frozenset[str]:
    """The sections asked for: every one without the parameter, else the named subset."""
    if sections is None:
        return frozenset(SOURCES)
    names = sections.split(",")
    if any(name not in SOURCES for name in names):
        raise HTTPException(status_code=422, detail="invalid_sections")
    return frozenset(names)


@router.get("/today")
def today(
    request: Request, sections: Annotated[str | None, Query(max_length=64)] = None
) -> dict[str, Any]:
    """The digest. ``sections`` (comma-separated ``mail``, ``events``, ``deadlines``) limits it:
    sections not named are left out of the response, and so are their ``updated_at`` entries."""
    wanted = _requested(sections)
    state = request.app.state
    cache: TodayCache = state.today
    now = state.clock()
    stale_after = timedelta(minutes=STALE_AFTER_REFRESHES * state.settings.today_refresh_minutes)
    snapshot = cache.snapshot()
    body: dict[str, Any] = {"generated_at": now.isoformat()}
    unavailable: list[str] = []
    stale: list[str] = []
    updated_at: dict[str, str | None] = {}
    for source in SOURCES:
        if source not in wanted:
            continue
        current = snapshot.get(source)
        body[source] = None
        updated_at[source] = None
        if current is None:
            continue
        if not current.has_data or current.updated_at is None:
            unavailable.append(source)
            continue
        body[source] = current.data
        updated_at[source] = current.updated_at.isoformat()
        if current.failed or now - current.updated_at > stale_after:
            stale.append(source)
    body["unavailable"] = unavailable
    body["stale"] = stale
    body["updated_at"] = updated_at
    return body
