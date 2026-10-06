"""File search for the phone's Files screen.

Runs the same READ tools the agent uses (files_search, drive_search), so the phone sees exactly
the allowed local folders and Drive accounts the agent sees. Nothing here goes to the LLM and
nothing is written: sending or sharing a file is still a WRITE tool proposed through chat and
approved on the phone.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from agent.core.tools import ToolKind, ToolRegistry

log = logging.getLogger(__name__)

router = APIRouter()


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _run(registry: ToolRegistry, name: str, args: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The tool's results, or None when the tool is not configured. Only READ tools run here."""
    tool = registry.get(name)
    if tool is None or tool.kind is not ToolKind.READ:
        return None
    result = tool.run(args)
    return result if isinstance(result, list) else []


@router.get("/files/search")
def search_files(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> dict[str, Any]:
    registry: ToolRegistry = request.app.state.registry
    out: dict[str, Any] = {"local": None, "drive": None, "errors": []}

    try:
        local = _run(registry, "files_search", {"query": q, "limit": limit})
    except Exception as exc:  # one source failing must not hide the other
        log.warning("files_search failed: %s", type(exc).__name__)
        out["errors"].append("local")
    else:
        if local is not None:
            out["local"] = [
                {
                    "source": "local",
                    "path": str(h.get("path", "")),
                    "name": str(h.get("name", "")),
                    "size": _int_or_none(h.get("size")),
                    "modified": h.get("modified"),
                }
                for h in local
            ]

    try:
        drive = _run(registry, "drive_search", {"query": q, "limit": limit})
    except Exception as exc:
        log.warning("drive_search failed: %s", type(exc).__name__)
        out["errors"].append("drive")
    else:
        if drive is not None:
            out["drive"] = [
                {
                    "source": "drive",
                    "account": str(h.get("account", "")),
                    "id": str(h.get("id", "")),
                    "name": str(h.get("name", "")),
                    "mime": h.get("mime"),
                    "size": _int_or_none(h.get("size")),
                    "modified": h.get("modified"),
                }
                for h in drive
            ]
    return out
