"""``ClassroomApi`` over google-api-python-client. Read-only: no write method exists."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from googleapiclient.discovery import build

from agent.connectors.classroom import MAX_COURSES, MAX_COURSEWORK
from agent.connectors.google_auth import (
    CLASSROOM_ANNOUNCEMENTS,
    CLASSROOM_COURSES,
    CLASSROOM_COURSEWORK,
    CLASSROOM_MATERIALS,
    GoogleAuth,
)

_RETRIES = 3
_PAGE_SIZE = 100


class GoogleClassroomApi:
    def __init__(self, service: Any, after_call: Callable[[], None] | None = None) -> None:
        self._service = service
        self._after_call = after_call

    def _execute(self, request: Any) -> Any:
        result = request.execute(num_retries=_RETRIES)
        if self._after_call is not None:
            self._after_call()
        return result

    def _paginate(
        self, make_request: Callable[[str | None], Any], key: str, cap: int
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        while len(items) < cap:
            result = self._execute(make_request(token))
            items.extend(result.get(key, []))
            token = result.get("nextPageToken")
            if not token:
                break
        return items[:cap]

    def list_courses(self) -> list[dict[str, Any]]:
        return self._paginate(
            lambda token: self._service.courses().list(
                courseStates=["ACTIVE"], pageSize=_PAGE_SIZE, pageToken=token
            ),
            "courses",
            MAX_COURSES,
        )

    def list_coursework(self, course_id: str) -> list[dict[str, Any]]:
        return self._paginate(
            lambda token: (
                self._service.courses()
                .courseWork()
                .list(courseId=course_id, pageSize=_PAGE_SIZE, pageToken=token)
            ),
            "courseWork",
            MAX_COURSEWORK,
        )

    def list_announcements(self, course_id: str, limit: int) -> list[dict[str, Any]]:
        result = self._execute(
            self._service.courses()
            .announcements()
            .list(courseId=course_id, pageSize=limit, orderBy="updateTime desc")
        )
        items: list[dict[str, Any]] = result.get("announcements", [])
        return items[:limit]

    def list_materials(self, course_id: str, limit: int) -> list[dict[str, Any]]:
        result = self._execute(
            self._service.courses().courseWorkMaterials().list(courseId=course_id, pageSize=limit)
        )
        items: list[dict[str, Any]] = result.get("courseWorkMaterial", [])
        return items[:limit]


def build_classroom_api(account: str, auth: GoogleAuth) -> GoogleClassroomApi:
    credentials = auth.credentials(
        account,
        [CLASSROOM_COURSES, CLASSROOM_COURSEWORK, CLASSROOM_ANNOUNCEMENTS, CLASSROOM_MATERIALS],
    )
    service = build("classroom", "v1", credentials=credentials, cache_discovery=False)
    return GoogleClassroomApi(service, auth.persist_hook(account))
