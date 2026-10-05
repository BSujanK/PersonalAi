"""Classroom tools. Everything here is read-only and returns untrusted data."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from agent.connectors.classroom import ClassroomApi, due_instant, due_of
from agent.core.clock import Clock
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.workspace.calendar_tools import check_account, check_int

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ApiFor = Callable[[str], ClassroomApi]


def _check_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _attachment_titles(material: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for attachment in material.get("materials") or []:
        if not isinstance(attachment, dict):
            continue
        for value in attachment.values():
            if isinstance(value, dict):
                inner = value.get("driveFile") if "title" not in value else value
                if isinstance(inner, dict) and isinstance(inner.get("title"), str):
                    titles.append(inner["title"][:200])
    return titles


def _due_text(due: date | datetime) -> str:
    return due.isoformat()


def register_classroom_tools(
    registry: ToolRegistry, api_for: _ApiFor, accounts: Sequence[str], clock: Clock
) -> None:
    def chosen(args: dict[str, Any]) -> list[str]:
        account = args.get("account")
        if account is None:
            return list(accounts)
        return [check_account(account, accounts)]

    def courses(args: dict[str, Any]) -> Any:
        return [
            {
                "account": account,
                "id": course.get("id", ""),
                "name": course.get("name", ""),
                "section": course.get("section", ""),
            }
            for account in chosen(args)
            for course in api_for(account).list_courses()
        ]

    def coursework(args: dict[str, Any]) -> Any:
        wanted = args.get("course_id")
        if wanted is not None:
            _check_id(wanted, "course_id")
        days = check_int(args.get("days", 14), 1, 60, "days")
        now = clock()
        horizon = now + timedelta(days=days)
        found: list[tuple[datetime, dict[str, Any]]] = []
        for account in chosen(args):
            api = api_for(account)
            for course in api.list_courses():
                course_id = course.get("id", "")
                if wanted is not None and course_id != wanted:
                    continue
                for work in api.list_coursework(course_id):
                    due = due_of(work)
                    if due is None or not now < due_instant(due) <= horizon:
                        continue
                    found.append(
                        (
                            due_instant(due),
                            {
                                "account": account,
                                "course_id": course_id,
                                "course": course.get("name", ""),
                                "id": work.get("id", ""),
                                "title": work.get("title", ""),
                                "due": _due_text(due),
                                "description": _text(work.get("description"), 2000),
                            },
                        )
                    )
        found.sort(key=lambda pair: pair[0])
        return [item for _, item in found]

    def announcements(args: dict[str, Any]) -> Any:
        account = check_account(args.get("account"), accounts)
        course_id = _check_id(args.get("course_id"), "course_id")
        limit = check_int(args.get("limit", 10), 1, 20, "limit")
        return [
            {
                "id": item.get("id", ""),
                "text": _text(item.get("text"), 2000),
                "created": item.get("creationTime", ""),
            }
            for item in api_for(account).list_announcements(course_id, limit)
        ]

    def materials(args: dict[str, Any]) -> Any:
        account = check_account(args.get("account"), accounts)
        course_id = _check_id(args.get("course_id"), "course_id")
        limit = check_int(args.get("limit", 10), 1, 20, "limit")
        return [
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "description": _text(item.get("description"), 1000),
                "attachments": _attachment_titles(item),
            }
            for item in api_for(account).list_materials(course_id, limit)
        ]

    account_any = {
        "account": {
            "type": "string",
            "description": "Only this Classroom account; leave it out to cover every account.",
        }
    }
    account_copied = {
        "account": {
            "type": "string",
            "description": "The account field of the course in classroom_courses, copied exactly.",
        }
    }
    course_copied = {
        "type": "string",
        "description": (
            "The id field of the course in classroom_courses (a short code such as c1). "
            "It is never the course name."
        ),
    }
    limit_prop = {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
        "description": "Maximum number of items (default 10).",
    }
    course_props = {**account_copied, "course_id": course_copied, "limit": limit_prop}
    for name, description, props, required, run in (
        (
            "classroom_courses",
            "List the owner's active Google Classroom courses. Call this first whenever the "
            "owner names a course (for example History): every course has an id and an account, "
            "and the other classroom tools need those, not the course name.",
            account_any,
            [],
            courses,
        ),
        (
            "classroom_coursework",
            "List upcoming Classroom assignments with their due dates, soonest first. To answer "
            "'what is due in <course>', first find the course with classroom_courses, then call "
            "this with that course's id as course_id; leave course_id out to list every course. "
            "Each item has title, due (ISO date or datetime), course, course_id, id and account. "
            "When the owner wants a deadline on their calendar, use calendar_add_deadline with "
            "these values.",
            {
                **account_any,
                "course_id": course_copied,
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 60,
                    "description": "How many days ahead to look (default 14; use 60 for the term).",
                },
            },
            [],
            coursework,
        ),
        (
            "classroom_announcements",
            "Recent announcements posted by teachers in ONE Classroom course (they often carry "
            "exam dates, room changes and deadlines). Needs the account and id of the course "
            "from classroom_courses, so call that first.",
            course_props,
            ["account", "course_id"],
            announcements,
        ),
        (
            "classroom_materials",
            "Recent class materials (slides, readings, files) of ONE Classroom course. Needs "
            "the account and id of the course from classroom_courses, so call that first.",
            course_props,
            ["account", "course_id"],
            materials,
        ),
    ):
        registry.register(
            Tool(
                name=name,
                description=description,
                parameters={
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": False,
                },
                kind=ToolKind.READ,
                run=run,
            )
        )
