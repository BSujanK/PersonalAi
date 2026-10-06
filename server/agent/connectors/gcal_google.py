"""``CalendarApi`` over google-api-python-client. Never notifies guests."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.connectors.gcal import EventNotFound, NotOwnEvent
from agent.connectors.google_auth import CALENDAR_EVENTS, GoogleAuth
from agent.proactive.autocal import MARKER_KEY, check_own_body

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


def _has_marker(event: dict[str, Any], marker: str) -> bool:
    private = (event.get("extendedProperties") or {}).get("private") or {}
    value = private.get(MARKER_KEY)
    return isinstance(value, str) and hmac.compare_digest(value, marker)


def _check_deletable(event: dict[str, Any], marker: str) -> None:
    """Only the event the automatic path created (its own marker), with no guests, owner's own."""
    if not _has_marker(event, marker) or event.get("attendees"):
        raise NotOwnEvent("not an automatically added event")
    for role in ("organizer", "creator"):
        person = event.get(role)
        if person is not None and (not isinstance(person, dict) or person.get("self") is not True):
            raise NotOwnEvent("not an event of the owner")


class GoogleOwnCalendarApi:
    """``OwnCalendarApi`` over google-api-python-client: primary calendar only, never notifies."""

    def __init__(self, service: Any, after_call: Callable[[], None] | None = None) -> None:
        self._service = service
        self._after_call = after_call

    def _execute(self, request: Any) -> Any:
        result = request.execute(num_retries=_RETRIES)
        if self._after_call is not None:
            self._after_call()
        return result

    def insert_own_event(self, body: dict[str, Any]) -> dict[str, Any]:
        check_own_body(body)
        event: dict[str, Any] = self._execute(
            self._service.events().insert(
                calendarId=_CALENDAR,
                body=body,
                sendUpdates="none",
                conferenceDataVersion=0,
                supportsAttachments=False,
            )
        )
        return event

    def find_own(self, marker: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = self._execute(
            self._service.events().list(
                calendarId=_CALENDAR,
                privateExtendedProperty=f"{MARKER_KEY}={marker}",
                maxResults=_FIND_LIMIT,
            )
        ).get("items", [])
        return items

    def delete_own(self, event_id: str, marker: str) -> None:
        try:
            event: dict[str, Any] = self._execute(
                self._service.events().get(calendarId=_CALENDAR, eventId=event_id)
            )
            _check_deletable(event, marker)
            self._execute(
                self._service.events().delete(
                    calendarId=_CALENDAR, eventId=event_id, sendUpdates="none"
                )
            )
        except HttpError as exc:
            if _status(exc) in (404, 410):
                raise EventNotFound(event_id) from None
            raise


def build_own_calendar_api(account: str, auth: GoogleAuth) -> GoogleOwnCalendarApi:
    credentials = auth.credentials(account, [CALENDAR_EVENTS])
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return GoogleOwnCalendarApi(service, auth.persist_hook(account))


def build_calendar_api(account: str, auth: GoogleAuth) -> GoogleCalendarApi:
    credentials = auth.credentials(account, [CALENDAR_EVENTS])
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return GoogleCalendarApi(service, auth.persist_hook(account))
