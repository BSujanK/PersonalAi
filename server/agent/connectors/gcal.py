"""Google Calendar protocol the rest of the agent depends on (primary calendar only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class EventNotFound(LookupError):
    """The event no longer exists (deleted or gone)."""


class CalendarApi(Protocol):
    def list_events(
        self, time_min: datetime, time_max: datetime, query: str | None, max_results: int
    ) -> list[dict[str, Any]]: ...

    def find_private(self, key: str, value: str) -> list[dict[str, Any]]: ...

    def get_event(self, event_id: str) -> dict[str, Any]: ...

    def insert_event(self, body: dict[str, Any]) -> dict[str, Any]: ...

    def patch_event(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]: ...
