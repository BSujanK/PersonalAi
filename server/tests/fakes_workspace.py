"""In-memory Calendar and Classroom APIs. Synthetic data only."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from agent.connectors.gcal import EventNotFound


class FakeCalendarApi:
    def __init__(self, account: str = "me@example.com") -> None:
        self.account = account
        self.events: dict[str, dict[str, Any]] = {}
        self.list_calls: list[tuple[datetime, datetime, str | None, int]] = []
        self.find_calls: list[tuple[str, str]] = []
        self.inserted: list[dict[str, Any]] = []
        self.patched: list[tuple[str, dict[str, Any]]] = []
        self.fail_get = False
        self._next = 1

    def add_event(self, **event: Any) -> dict[str, Any]:
        event.setdefault("id", f"ev{self._next}")
        self._next += 1
        self.events[event["id"]] = event
        return event

    def list_events(
        self, time_min: datetime, time_max: datetime, query: str | None, max_results: int
    ) -> list[dict[str, Any]]:
        self.list_calls.append((time_min, time_max, query, max_results))
        found = [e for e in self.events.values() if query is None or query in e.get("summary", "")]
        return copy.deepcopy(found[:max_results])

    def find_private(self, key: str, value: str) -> list[dict[str, Any]]:
        self.find_calls.append((key, value))
        return [
            e
            for e in self.events.values()
            if e.get("extendedProperties", {}).get("private", {}).get(key) == value
        ]

    def get_event(self, event_id: str) -> dict[str, Any]:
        if self.fail_get or event_id not in self.events:
            raise EventNotFound(event_id)
        return copy.deepcopy(self.events[event_id])

    def insert_event(self, body: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append(copy.deepcopy(body))
        return self.add_event(**copy.deepcopy(body))

    def patch_event(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if event_id not in self.events:
            raise EventNotFound(event_id)
        self.patched.append((event_id, copy.deepcopy(body)))
        self.events[event_id].update(copy.deepcopy(body))
        return copy.deepcopy(self.events[event_id])


class FakeClassroomApi:
    def __init__(self) -> None:
        self.courses: list[dict[str, Any]] = []
        self.coursework: dict[str, list[dict[str, Any]]] = {}
        self.announcements: dict[str, list[dict[str, Any]]] = {}
        self.materials: dict[str, list[dict[str, Any]]] = {}
        self.fail: Exception | None = None

    def add_course(self, course_id: str, name: str, section: str = "") -> None:
        self.courses.append({"id": course_id, "name": name, "section": section})

    def list_courses(self) -> list[dict[str, Any]]:
        if self.fail is not None:
            raise self.fail
        return list(self.courses)

    def list_coursework(self, course_id: str) -> list[dict[str, Any]]:
        return list(self.coursework.get(course_id, []))

    def list_announcements(self, course_id: str, limit: int) -> list[dict[str, Any]]:
        return list(self.announcements.get(course_id, []))[:limit]

    def list_materials(self, course_id: str, limit: int) -> list[dict[str, Any]]:
        return list(self.materials.get(course_id, []))[:limit]


def due_fields(due: datetime | None, *, date_only: bool = False) -> dict[str, Any]:
    """The dueDate / dueTime keys of a Classroom coursework resource."""
    if due is None:
        return {}
    fields: dict[str, Any] = {"dueDate": {"year": due.year, "month": due.month, "day": due.day}}
    if not date_only:
        fields["dueTime"] = {"hours": due.hour, "minutes": due.minute}
    return fields


class Workspace:
    """Approval engine plus calendar and classroom tools over fakes."""

    def __init__(self) -> None:
        from agent.core.approvals import ApprovalEngine
        from agent.core.audit import AuditLog
        from agent.core.tools import ToolRegistry
        from agent.store.crypto import FieldCipher
        from agent.store.db import Database
        from agent.store.keystore import KeyStore
        from agent.workspace.calendar_tools import register_calendar_tools
        from agent.workspace.classroom_tools import register_classroom_tools
        from agent.workspace.deadlines import register_deadline_tool
        from tests.support import DEVICE_ID, FakeClock

        self.calendars = {"me@example.com": FakeCalendarApi("me@example.com")}
        self.calendars["college@example.org"] = FakeCalendarApi("college@example.org")
        self.classrooms = {"college@example.org": FakeClassroomApi()}
        self.clock = FakeClock()
        self.approval_key = bytes(range(100, 132))
        self.db = Database(":memory:")
        keystore = KeyStore()
        keystore.set_bytes(f"approval_key:{DEVICE_ID}", self.approval_key)
        self.registry = ToolRegistry()
        self.engine = ApprovalEngine(
            self.db,
            FieldCipher(bytes(range(32))),
            self.registry,
            AuditLog(self.db, self.clock),
            keystore,
            self.clock,
        )
        accounts = list(self.calendars)
        register_calendar_tools(self.registry, self.calendars.__getitem__, accounts, self.clock)
        register_classroom_tools(
            self.registry, self.classrooms.__getitem__, list(self.classrooms), self.clock
        )
        register_deadline_tool(self.registry, self.calendars.__getitem__, accounts)

    def tool(self, name: str) -> Any:
        tool = self.registry.get(name)
        assert tool is not None
        return tool
