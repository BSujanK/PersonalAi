"""The calendar_add_deadline tool: a Classroom due date as a calendar event, after approval."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from agent.connectors.gcal import CalendarApi
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.workspace.calendar_tools import (
    NO_GUESTS,
    check_account,
    check_text,
    describe_when,
    parse_when,
    time_field,
)

TOOL_NAME = "calendar_add_deadline"
PROPERTY_KEY = "personalai_coursework"
DESCRIPTION = "Added from Google Classroom."
BLOCK = timedelta(minutes=30)
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ACCOUNT_RE = re.compile(r"[^\s/]{1,254}")


@dataclass(frozen=True)
class _Deadline:
    calendar_account: str
    key: str
    summary: str
    start: date | datetime
    end: date | datetime

    def body(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "start": time_field(self.start),
            "end": time_field(self.end),
            "description": DESCRIPTION,
            "extendedProperties": {"private": {PROPERTY_KEY: self.key}},
        }


def _parse(args: dict[str, Any], calendar_accounts: Sequence[str]) -> _Deadline:
    calendar_account = check_account(args.get("calendar_account"), calendar_accounts)
    classroom_account = args.get("classroom_account")
    if not isinstance(classroom_account, str) or not _ACCOUNT_RE.fullmatch(classroom_account):
        raise ValueError("invalid classroom_account")
    ids: list[str] = []
    for name in ("course_id", "coursework_id"):
        value = args.get(name)
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise ValueError(f"invalid {name}")
        ids.append(value)
    title = check_text(args.get("title"), "title", limit=200, minimum=1, one_line=True)
    course = check_text(args.get("course"), "course", limit=200, minimum=1, one_line=True)
    due = parse_when(args.get("due"), "due")
    start: date | datetime
    end: date | datetime
    if isinstance(due, datetime):
        start, end = due - BLOCK, due
    else:
        start, end = due, due + timedelta(days=1)
    return _Deadline(
        calendar_account,
        "/".join([classroom_account, *ids]),
        f"Due: {title} ({course})",
        start,
        end,
    )


def register_deadline_tool(
    registry: ToolRegistry,
    calendar_api_for: Callable[[str], CalendarApi],
    calendar_accounts: Sequence[str],
) -> None:
    def preview(args: dict[str, Any]) -> str:
        item = _parse(args, calendar_accounts)
        return "\n".join(
            [
                f"Add deadline to the calendar of {item.calendar_account}",
                f"Title: {item.summary}",
                f"When: {describe_when(item.start, item.end)}",
                f"Description: {DESCRIPTION}",
                NO_GUESTS,
            ]
        )

    def run(args: dict[str, Any]) -> Any:
        item = _parse(args, calendar_accounts)
        api = calendar_api_for(item.calendar_account)
        if api.find_private(PROPERTY_KEY, item.key):
            return {"ok": 0, "duplicate": True}
        created = api.insert_event(item.body())
        return {"ok": 1, "id": created["id"]}

    registry.register(
        Tool(
            name=TOOL_NAME,
            description=(
                "Put a Classroom assignment's due date on the owner's calendar (no guests are "
                "invited; requires the owner's approval). Use it after classroom_coursework "
                "found the assignment, copying that item's values: classroom_account is its "
                "account, plus its course_id, coursework_id (its id), title, course (its course "
                "name) and due. calendar_account is the calendar to add it to, one of the "
                "calendar accounts. For anything that did not come from Classroom, use "
                "calendar_create_event instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "calendar_account": {
                        "type": "string",
                        "description": "The calendar account the event is added to.",
                    },
                    "classroom_account": {
                        "type": "string",
                        "description": "The account field of the classroom_coursework item.",
                    },
                    "course_id": {
                        "type": "string",
                        "description": "The course_id field of the classroom_coursework item.",
                    },
                    "coursework_id": {
                        "type": "string",
                        "description": "The id field of the classroom_coursework item.",
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "The assignment title, copied from the item.",
                    },
                    "course": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "The course name, copied from the item's course field.",
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "The due field of the item, unchanged: an ISO datetime with offset, "
                            "or an ISO date for an all-day deadline."
                        ),
                    },
                },
                "required": [
                    "calendar_account",
                    "classroom_account",
                    "course_id",
                    "coursework_id",
                    "title",
                    "course",
                    "due",
                ],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=run,
            preview=preview,
        )
    )
