"""Google Calendar protocol the rest of the agent depends on (primary calendar only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class EventNotFound(LookupError):
    """The event no longer exists (deleted or gone)."""


class NotOwnEvent(PermissionError):
    """The event was not created by the agent's automatic path, so it must not be touched."""


class OwnCalendarApi(Protocol):
    """The narrow calendar surface of the one write that needs no approval (auto-added deadlines).

    Deliberately small: no patch, update or move, and no calendar id (always the primary one).
    It can only create an agent-marked event, find it by its marker and delete it again, and only
    when the live event still carries that exact marker.
    """

    def insert_own_event(self, body: dict[str, Any]) -> dict[str, Any]: ...

    def find_own(self, marker: str) -> list[dict[str, Any]]: ...

    def delete_own(self, event_id: str, marker: str) -> None: ...


class CalendarApi(Protocol):
    def list_events(
        self, time_min: datetime, time_max: datetime, query: str | None, max_results: int
    ) -> list[dict[str, Any]]: ...

    def find_private(self, key: str, value: str) -> list[dict[str, Any]]: ...

    def get_event(self, event_id: str) -> dict[str, Any]: ...

    def insert_event(self, body: dict[str, Any]) -> dict[str, Any]: ...

    def patch_event(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]: ...
