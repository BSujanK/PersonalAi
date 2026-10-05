"""Google Classroom protocol (read-only) and due-date parsing."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

MAX_COURSES = 100
MAX_COURSEWORK = 200


class ClassroomApi(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...

    def list_coursework(self, course_id: str) -> list[dict[str, Any]]: ...

    def list_announcements(self, course_id: str, limit: int) -> list[dict[str, Any]]: ...

    def list_materials(self, course_id: str, limit: int) -> list[dict[str, Any]]: ...


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("not an integer")
    return value


def due_of(coursework: dict[str, Any]) -> datetime | date | None:
    """The due moment: an aware UTC datetime, a date when no time is set, or None."""
    raw = coursework.get("dueDate")
    if not isinstance(raw, dict):
        return None
    try:
        day = date(_int(raw.get("year")), _int(raw.get("month")), _int(raw.get("day")))
        if "dueTime" not in coursework:
            return day
        clock = coursework["dueTime"]
        if not isinstance(clock, dict):
            return None
        return datetime.combine(
            day, time(_int(clock.get("hours", 0)), _int(clock.get("minutes", 0))), tzinfo=UTC
        )
    except ValueError:
        return None


def due_instant(due: datetime | date) -> datetime:
    """When a due value passes: a date-only due lasts until the end of that day (UTC)."""
    if isinstance(due, datetime):
        return due
    return datetime.combine(due + timedelta(days=1), time.min, tzinfo=UTC)
