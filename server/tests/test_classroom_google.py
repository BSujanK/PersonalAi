from __future__ import annotations

import json
from typing import Any

import pytest

from agent.connectors.classroom_google import GoogleClassroomApi, build_classroom_api
from agent.connectors.google_auth import (
    CLASSROOM_ANNOUNCEMENTS,
    CLASSROOM_COURSES,
    CLASSROOM_COURSEWORK,
    CLASSROOM_MATERIALS,
    CLIENT_SECRET_NAME,
    GoogleAuth,
    GoogleNotConfigured,
    token_secret_name,
)
from agent.store.keystore import KeyStore

ACCOUNT = "student@example.org"
ALL_SCOPES = [CLASSROOM_COURSES, CLASSROOM_COURSEWORK, CLASSROOM_ANNOUNCEMENTS, CLASSROOM_MATERIALS]


class _Request:
    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self, num_retries: int = 0) -> Any:
        return self._result


class _Service:
    """Serves `pages` in order for every list call and records the call arguments."""

    def __init__(self, *pages: dict[str, Any]) -> None:
        self._pages = list(pages)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def courses(self) -> _Service:
        return self

    def courseWork(self) -> _Named:
        return _Named(self, "courseWork")

    def announcements(self) -> _Named:
        return _Named(self, "announcements")

    def courseWorkMaterials(self) -> _Named:
        return _Named(self, "materials")

    def list(self, **kwargs: Any) -> _Request:
        return self.record("courses", kwargs)

    def record(self, name: str, kwargs: dict[str, Any]) -> _Request:
        self.calls.append((name, kwargs))
        return _Request(self._pages.pop(0) if len(self._pages) > 1 else self._pages[0])


class _Named:
    def __init__(self, service: _Service, name: str) -> None:
        self._service = service
        self._name = name

    def list(self, **kwargs: Any) -> _Request:
        return self._service.record(self._name, kwargs)


def _items(prefix: str, n: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}{i}"} for i in range(n)]


def test_courses_request_active_only_and_follow_pages() -> None:
    service = _Service(
        {"courses": _items("a", 3), "nextPageToken": "t1"}, {"courses": _items("b", 2)}
    )
    found = GoogleClassroomApi(service).list_courses()
    assert [c["id"] for c in found] == ["a0", "a1", "a2", "b0", "b1"]
    first, second = (kw for _, kw in service.calls)
    assert first["courseStates"] == ["ACTIVE"] and first["pageToken"] is None
    assert second["pageToken"] == "t1"


def test_courses_are_capped_at_100() -> None:
    service = _Service({"courses": _items("c", 60), "nextPageToken": "more"})
    assert len(GoogleClassroomApi(service).list_courses()) == 100
    assert len(service.calls) == 2


def test_coursework_paginates_and_caps_at_200() -> None:
    service = _Service({"courseWork": _items("w", 100), "nextPageToken": "more"})
    found = GoogleClassroomApi(service).list_coursework("c1")
    assert len(found) == 200 and len(service.calls) == 2
    assert service.calls[0][1]["courseId"] == "c1"


def test_coursework_stops_without_next_page() -> None:
    service = _Service({"courseWork": _items("w", 5)})
    assert len(GoogleClassroomApi(service).list_coursework("c1")) == 5
    assert len(service.calls) == 1


def test_announcements_and_materials_request_shapes() -> None:
    service = _Service({"announcements": _items("n", 5), "courseWorkMaterial": _items("m", 5)})
    api = GoogleClassroomApi(service)
    assert len(api.list_announcements("c1", 3)) == 3
    assert len(api.list_materials("c1", 2)) == 2
    (_, ann), (_, mat) = service.calls
    assert ann == {"courseId": "c1", "pageSize": 3, "orderBy": "updateTime desc"}
    assert mat == {"courseId": "c1", "pageSize": 2}


def test_api_has_no_write_methods() -> None:
    public = {n for n in dir(GoogleClassroomApi) if not n.startswith("_")}
    assert public == {"list_courses", "list_coursework", "list_announcements", "list_materials"}


def test_after_call_hook_runs_per_request() -> None:
    hits: list[int] = []
    service = _Service({"courses": [], "nextPageToken": "x"}, {"courses": []})
    GoogleClassroomApi(service, lambda: hits.append(1)).list_courses()
    assert hits == [1, 1]


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


@pytest.mark.parametrize("missing", ALL_SCOPES)
def test_build_requires_all_four_scopes(missing: str) -> None:
    with pytest.raises(GoogleNotConfigured):
        build_classroom_api(ACCOUNT, _auth([s for s in ALL_SCOPES if s != missing]))


def test_build_succeeds_with_all_scopes() -> None:
    api = build_classroom_api(ACCOUNT, _auth(ALL_SCOPES))
    assert api._service._http.credentials.refresh_token == "rt"
