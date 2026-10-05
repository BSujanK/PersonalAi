from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from agent.connectors.gcal import EventNotFound
from agent.connectors.gcal_google import GoogleCalendarApi, build_calendar_api
from agent.connectors.google_auth import (
    CALENDAR_EVENTS,
    CLIENT_SECRET_NAME,
    GMAIL_MODIFY,
    GoogleAuth,
    GoogleNotConfigured,
    token_secret_name,
)
from agent.store.keystore import KeyStore

ACCOUNT = "me@example.com"


class _Resp:
    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "x"


class _Request:
    def __init__(self, result: Any = None, status: int | None = None) -> None:
        self._result = result
        self._status = status

    def execute(self, num_retries: int = 0) -> Any:
        if self._status is not None:
            raise HttpError(_Resp(self._status), b"{}")  # type: ignore[no-untyped-call]
        return self._result


class _Service:
    def __init__(self, request: _Request) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._request = request

    def events(self) -> _Service:
        return self

    def __getattr__(self, name: str) -> Any:
        def method(**kwargs: Any) -> _Request:
            self.calls.append((name, kwargs))
            return self._request

        return method


def _kwargs(service: _Service, name: str) -> dict[str, Any]:
    return next(kw for n, kw in service.calls if n == name)


def test_list_events_expands_recurrences_in_start_order() -> None:
    service = _Service(_Request({"items": [{"id": "a"}]}))
    low = datetime(2026, 10, 5, 12, tzinfo=UTC)
    high = datetime(2026, 10, 12, 12, tzinfo=UTC)
    assert GoogleCalendarApi(service).list_events(low, high, "exam", 999) == [{"id": "a"}]
    kw = _kwargs(service, "list")
    assert kw["calendarId"] == "primary"
    assert kw["singleEvents"] is True and kw["orderBy"] == "startTime"
    assert kw["timeMin"] == "2026-10-05T12:00:00+00:00"
    assert kw["timeMax"] == "2026-10-12T12:00:00+00:00"
    assert kw["q"] == "exam" and kw["maxResults"] == 250


def test_find_private_uses_private_extended_property() -> None:
    service = _Service(_Request({}))
    assert GoogleCalendarApi(service).find_private("k", "a/b/c") == []
    kw = _kwargs(service, "list")
    assert kw["privateExtendedProperty"] == "k=a/b/c"
    assert kw["calendarId"] == "primary"


def test_writes_never_notify_guests() -> None:
    service = _Service(_Request({"id": "e1"}))
    api = GoogleCalendarApi(service)
    body = {"summary": "x"}
    assert api.insert_event(body) == {"id": "e1"}
    api.patch_event("e1", body)
    insert, patch = _kwargs(service, "insert"), _kwargs(service, "patch")
    assert insert["sendUpdates"] == "none" and insert["body"] == body
    assert patch["sendUpdates"] == "none" and patch["eventId"] == "e1"


@pytest.mark.parametrize("status", [404, 410])
def test_gone_events_map_to_event_not_found(status: int) -> None:
    api = GoogleCalendarApi(_Service(_Request(status=status)))
    with pytest.raises(EventNotFound):
        api.get_event("e1")
    with pytest.raises(EventNotFound):
        api.patch_event("e1", {"summary": "x"})


def test_other_errors_propagate() -> None:
    api = GoogleCalendarApi(_Service(_Request(status=500)))
    with pytest.raises(HttpError):
        api.get_event("e1")
    with pytest.raises(HttpError):
        api.insert_event({})


def test_after_call_hook_runs() -> None:
    hits: list[int] = []
    GoogleCalendarApi(_Service(_Request({"items": []})), lambda: hits.append(1)).find_private(
        "k", "v"
    )
    assert hits == [1]


def _auth(scopes: list[str]) -> GoogleAuth:
    keystore = KeyStore()
    keystore.set(
        CLIENT_SECRET_NAME,
        json.dumps({"installed": {"client_id": "cid", "client_secret": "csec"}}),
    )
    keystore.set(
        token_secret_name(ACCOUNT),
        json.dumps({"refresh_token": "rt", "token": "at", "scopes": scopes}),
    )
    return GoogleAuth(keystore)


def test_build_requires_calendar_scope() -> None:
    with pytest.raises(GoogleNotConfigured):
        build_calendar_api(ACCOUNT, _auth([GMAIL_MODIFY]))
    with pytest.raises(GoogleNotConfigured):
        build_calendar_api(ACCOUNT, GoogleAuth(KeyStore()))


def test_build_uses_shared_credentials() -> None:
    api = build_calendar_api(ACCOUNT, _auth([GMAIL_MODIFY, CALENDAR_EVENTS]))
    credentials = api._service._http.credentials
    assert credentials.refresh_token == "rt"
    assert CALENDAR_EVENTS in credentials.scopes
    assert json.loads(credentials.to_json())["client_id"] == "cid"
