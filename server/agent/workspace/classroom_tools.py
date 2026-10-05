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

    account_prop = {
        "account": {
            "type": "string",
            "description": "The course's account value from classroom_courses, copied exactly.",
        }
    }
    course_id_prop = {
        "type": "string",
        "description": "The course's id value from classroom_courses (not its name).",
    }
    course_props = {
        **account_prop,
        "course_id": course_id_prop,
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    }
    for name, description, props, required, run in (
        (
            "classroom_courses",
            "List the owner's active Google Classroom courses with each course's id, name and "
            "account. Call this first whenever the owner mentions a course or class, then pass "
            "the id and account to the other classroom tools.",
            {"account": {"type": "string", "description": "Omit to list every account."}},
            [],
            courses,
        ),
        (
            "classroom_coursework",
            "List upcoming Classroom assignments, tests and quizzes with due dates, soonest "
            "first. Each item has a due value to use for a calendar event or reminder. Pass "
            "course_id and account from classroom_courses for one course, or omit both for all.",
            {
                **account_prop,
                "course_id": course_id_prop,
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 60,
                    "description": "How many days ahead to look (default 14).",
                },
            },
            [],
            coursework,
        ),
        (
            "classroom_announcements",
            "Recent teacher announcements (posts) in one Classroom course, newest first. Needs "
            "the course's id and account from classroom_courses.",
            course_props,
            ["account", "course_id"],
            announcements,
        ),
        (
            "classroom_materials",
            "Recent class materials (readings, slides, files) in one Classroom course. Needs the "
            "course's id and account from classroom_courses.",
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
