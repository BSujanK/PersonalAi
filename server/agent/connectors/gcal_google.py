"""``CalendarApi`` over google-api-python-client. Never notifies guests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.connectors.gcal import EventNotFound
from agent.connectors.google_auth import CALENDAR_EVENTS, GoogleAuth

_RETRIES = 3
_CALENDAR = "primary"
_MAX_RESULTS = 250
_FIND_LIMIT = 10


def _status(exc: HttpError) -> int | None:
    status = getattr(exc.resp, "status", None)
    return int(status) if status is not None else None


class GoogleCalendarApi:
    def __init__(self, service: Any, after_call: Callable[[], None] | None = None) -> None:
        self._service = service
        self._after_call = after_call

    def _execute(self, request: Any) -> Any:
        result = request.execute(num_retries=_RETRIES)
        if self._after_call is not None:
            self._after_call()
        return result

    def _items(self, request: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = self._execute(request).get("items", [])
        return items

    def list_events(
        self, time_min: datetime, time_max: datetime, query: str | None, max_results: int
    ) -> list[dict[str, Any]]:
        return self._items(
            self._service.events().list(
                calendarId=_CALENDAR,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                q=query,
                maxResults=min(max_results, _MAX_RESULTS),
                singleEvents=True,
                orderBy="startTime",
            )
        )

    def find_private(self, key: str, value: str) -> list[dict[str, Any]]:
        return self._items(
            self._service.events().list(
                calendarId=_CALENDAR,
                privateExtendedProperty=f"{key}={value}",
                maxResults=_FIND_LIMIT,
            )
        )

    def get_event(self, event_id: str) -> dict[str, Any]:
        try:
            event: dict[str, Any] = self._execute(
                self._service.events().get(calendarId=_CALENDAR, eventId=event_id)
            )
        except HttpError as exc:
            if _status(exc) in (404, 410):
                raise EventNotFound(event_id) from None
            raise
        return event

    def insert_event(self, body: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = self._execute(
            self._service.events().insert(calendarId=_CALENDAR, body=body, sendUpdates="none")
        )
        return event

    def patch_event(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            event: dict[str, Any] = self._execute(
                self._service.events().patch(
                    calendarId=_CALENDAR, eventId=event_id, body=body, sendUpdates="none"
                )
            )
        except HttpError as exc:
            if _status(exc) in (404, 410):
                raise EventNotFound(event_id) from None
            raise
        return event


def build_calendar_api(account: str, auth: GoogleAuth) -> GoogleCalendarApi:
    credentials = auth.credentials(account, [CALENDAR_EVENTS])
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return GoogleCalendarApi(service, auth.persist_hook(account))
