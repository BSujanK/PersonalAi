"""Calendar tools. Reads are untrusted data; writes need approval and never invite guests."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from agent.connectors.gcal import CalendarApi
from agent.core.clock import Clock
from agent.core.tools import Tool, ToolKind, ToolRegistry

MAX_EVENT_DAYS = 14
NO_GUESTS = "No guests are invited."
NO_GUESTS_NOTIFIED = "No guests are invited or notified."
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EVENT_ID_RE = re.compile(r"[A-Za-z0-9_]{1,1024}")
_OLD_VALUE_PREVIEW = 500
_BREAKING = frozenset({"Cc", "Cf", "Zl", "Zp"})
_FIELD_LIMITS = {"summary": 200, "description": 2000, "location": 200}
_ApiFor = Callable[[str], CalendarApi]


def check_int(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def check_text(value: Any, name: str, *, limit: int, minimum: int = 0, one_line: bool) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) or len(value) > limit:
        raise ValueError(f"{name} must be a string of {minimum} to {limit} characters")
    if one_line and any(unicodedata.category(ch) in _BREAKING for ch in value):
        raise ValueError(f"{name} must be a single line")
    return value


def check_account(value: Any, accounts: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in accounts:
        raise ValueError("account is not configured")
    return value


def parse_when(value: Any, name: str) -> date | datetime:
    """An ISO date (all-day) or an ISO datetime that carries an explicit offset."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        if _DATE_RE.fullmatch(value):
            return date.fromisoformat(value)
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be an ISO date or datetime") from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} needs an explicit UTC offset")
    return moment


def time_field(moment: date | datetime) -> dict[str, str]:
    if isinstance(moment, datetime):
        return {"dateTime": moment.isoformat()}
    return {"date": moment.isoformat()}


def describe_when(start: date | datetime, end: date | datetime) -> str:
    return f"{start.isoformat()} → {end.isoformat()}"


@dataclass(frozen=True)
class _Span:
    start: date | datetime
    end: date | datetime


def _span(start: Any, end: Any) -> _Span:
    first, last = parse_when(start, "start"), parse_when(end, "end")
    if isinstance(first, datetime) != isinstance(last, datetime):
        raise ValueError("start and end must both be dates or both be datetimes")
    if last <= first:
        raise ValueError("end must be after start")
    if last - first > timedelta(days=MAX_EVENT_DAYS):
        raise ValueError(f"an event may last at most {MAX_EVENT_DAYS} days")
    return _Span(first, last)


def _start_key(event: dict[str, Any]) -> datetime:
    raw = event.get("start") or {}
    text = raw.get("dateTime") or raw.get("date") or ""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _summary(account: str, event: dict[str, Any]) -> dict[str, Any]:
    start, end = event.get("start") or {}, event.get("end") or {}
    return {
        "account": account,
        "id": event.get("id", ""),
        "summary": event.get("summary", ""),
        "start": start.get("dateTime") or start.get("date") or "",
        "end": end.get("dateTime") or end.get("date") or "",
        "all_day": "date" in start,
        "location": event.get("location", ""),
    }


def _event_when(event: dict[str, Any]) -> str:
    shown = _summary("", event)
    return f"{shown['start']} → {shown['end']}"


def _optional_text(args: dict[str, Any], name: str) -> str | None:
    if args.get(name) is None:
        return None
    return check_text(args[name], name, limit=_FIELD_LIMITS[name], one_line=name != "description")


_TEXT_PROPS: dict[str, Any] = {
    "summary": {
        "type": "string",
        "minLength": 1,
        "maxLength": 200,
        "description": "Short title, e.g. 'History midterm exam'.",
    },
    "start": {
        "type": "string",
        "description": "ISO 8601 datetime with the UTC offset from the source, or an ISO date "
        "for an all-day event.",
    },
    "end": {
        "type": "string",
        "description": "Same form as start. If the source gives no end time, use start plus "
        "one hour. A date end is exclusive.",
    },
    "description": {"type": "string", "maxLength": 2000},
    "location": {"type": "string", "maxLength": 200},
}


def register_calendar_tools(
    registry: ToolRegistry, api_for: _ApiFor, accounts: Sequence[str], clock: Clock
) -> None:
    def events(args: dict[str, Any]) -> Any:
        account = args.get("account")
        if account is not None:
            check_account(account, accounts)
        days = check_int(args.get("days", 7), 1, 31, "days")
        limit = check_int(args.get("limit", 20), 1, 50, "limit")
        query = args.get("query")
        if query is not None:
            query = check_text(query, "query", limit=100, one_line=True)
        now = clock()
        found: list[dict[str, Any]] = []
        for name in [account] if account is not None else accounts:
            for event in api_for(name).list_events(now, now + timedelta(days=days), query, limit):
                found.append({**_summary(name, event), "_key": _start_key(event)})
        found.sort(key=lambda e: e["_key"])
        return [{k: v for k, v in e.items() if k != "_key"} for e in found[:limit]]

    registry.register(
        Tool(
            name="calendar_events",
            description=(
                "List the owner's upcoming calendar events (with each event's account and id), "
                "from one account or all of them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Omit for every account."},
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 31,
                        "description": "How many days ahead (default 7).",
                    },
                    "query": {"type": "string", "maxLength": 100},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=events,
        )
    )

    def create_event(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        account = check_account(args.get("account"), accounts)
        summary = check_text(args.get("summary"), "summary", limit=200, minimum=1, one_line=True)
        span = _span(args.get("start"), args.get("end"))
        description = _optional_text(args, "description")
        location = _optional_text(args, "location")
        body: dict[str, Any] = {
            "summary": summary,
            "start": time_field(span.start),
            "end": time_field(span.end),
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        return account, body

    def create_preview(args: dict[str, Any]) -> str:
        account, body = create_event(args)
        start, end = parse_when(args["start"], "start"), parse_when(args["end"], "end")
        lines = [
            f"Create event on {account}",
            f"Title: {body['summary']}",
            f"When: {describe_when(start, end)}",
        ]
        if "location" in body:
            lines.append(f"Location: {body['location']}")
        if "description" in body:
            lines.append(f"Description:\n{body['description']}")
        lines.append(NO_GUESTS)
        return "\n".join(lines)

    def create_run(args: dict[str, Any]) -> Any:
        account, body = create_event(args)
        created = api_for(account).insert_event(body)
        return {"id": created["id"]}

    registry.register(
        Tool(
            name="calendar_create_event",
            description=(
                "Create an event on the owner's own calendar, e.g. an exam or deadline found "
                "with mail_read or classroom_coursework. No guests are ever invited. Requires "
                "the owner's approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": {
                        "type": "string",
                        "description": "Calendar account: the account value of the mail, course "
                        "or event the date came from, copied exactly.",
                    },
                    **_TEXT_PROPS,
                },
                "required": ["account", "summary", "start", "end"],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=create_run,
            preview=create_preview,
        )
    )

    def update_event(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        account = check_account(args.get("account"), accounts)
        event_id = args.get("event_id")
        if not isinstance(event_id, str) or not _EVENT_ID_RE.fullmatch(event_id):
            raise ValueError("invalid event_id")
        body: dict[str, Any] = {}
        if args.get("summary") is not None:
            body["summary"] = check_text(
                args["summary"], "summary", limit=200, minimum=1, one_line=True
            )
        for name in ("description", "location"):
            text = _optional_text(args, name)
            if text is not None:
                body[name] = text
        if (args.get("start") is None) != (args.get("end") is None):
            raise ValueError("start and end must be given together")
        if args.get("start") is not None:
            span = _span(args["start"], args["end"])
            body["start"], body["end"] = time_field(span.start), time_field(span.end)
        if not body:
            raise ValueError("at least one change is required")
        return account, event_id, body

    def update_preview(args: dict[str, Any]) -> str:
        account, event_id, body = update_event(args)
        try:
            old: dict[str, Any] | None = api_for(account).get_event(event_id)
        except Exception:  # preview must still list the new values; type is not shown
            old = None
        lines = [f"Change event on {account}"]
        if old is None:
            lines.append("(current details unavailable)")

        def change(label: str, before: str | None, after: str) -> None:
            shown = "(unavailable)" if before is None else (before[:_OLD_VALUE_PREVIEW] or "(none)")
            lines.append(f"{label}: {shown} → {after or '(none)'}")

        if "summary" in body:
            change("Title", old.get("summary", "") if old else None, body["summary"])
        if "start" in body:
            start, end = parse_when(args["start"], "start"), parse_when(args["end"], "end")
            change("When", _event_when(old) if old else None, describe_when(start, end))
        if "location" in body:
            change("Location", old.get("location", "") if old else None, body["location"])
        if "description" in body:
            change("Description", old.get("description", "") if old else None, body["description"])
        lines.append(NO_GUESTS_NOTIFIED)
        return "\n".join(lines)

    def update_run(args: dict[str, Any]) -> Any:
        account, event_id, body = update_event(args)
        patched = api_for(account).patch_event(event_id, body)
        return {"id": patched.get("id", event_id)}

    registry.register(
        Tool(
            name="calendar_update_event",
            description=(
                "Change the title, time, description or location of an existing event. "
                "Guests are never notified. Requires the owner's approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": {"type": "string"},
                    "event_id": {"type": "string", "pattern": "^[A-Za-z0-9_]{1,1024}$"},
                    **_TEXT_PROPS,
                },
                "required": ["account", "event_id"],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=update_run,
            preview=update_preview,
        )
    )
