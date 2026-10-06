"""Automatic calendar entries for deadlines: the one write that needs no approval (CLAUDE.md
rule 1 exception, owner decision 2026-10-06). It is narrow by construction:

* it only ever calls ``OwnCalendarApi`` (insert a marked event, find it, delete it again), which
  has no patch/update/move and no calendar id;
* ``check_own_body`` rejects any event field that could invite, notify or attach anything;
* only events this module created (recorded in ``auto_events``, marked with a private extended
  property) can be undone, so an event it did not create can never be deleted;
* the description never contains mail text, and logs carry ids and counts only.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from agent.connectors.gcal import EventNotFound, NotOwnEvent, OwnCalendarApi
from agent.core.audit import AuditLog
from agent.core.clock import Clock
from agent.proactive.deadlines import Deadline, DeadlineStore, deadline_target, due_span, local_tz
from agent.store.db import Database
from agent.workspace.calendar_tools import time_field

log = logging.getLogger(__name__)

MARKER_KEY = "personalai_auto"
BLOCK = timedelta(minutes=30)
MAX_PER_RUN = 10
MAX_PER_DAY = 30
MAX_AHEAD = timedelta(days=60)
SUMMARY_CHARS = 200
_MARKER_RE = re.compile(r"[0-9a-f]{32}")
_ALLOWED_KEYS = frozenset(
    {"summary", "description", "start", "end", "extendedProperties", "transparency", "reminders"}
)
_TIME_KEYS = frozenset({"date", "dateTime"})


class UnsafeAutoEvent(ValueError):
    """An automatic event body carried something it must never carry."""


def _check_time(value: object, name: str) -> None:
    if (
        not isinstance(value, dict)
        or len(value) != 1
        or not set(value) <= _TIME_KEYS
        or not all(isinstance(v, str) for v in value.values())
    ):
        raise UnsafeAutoEvent(f"{name} must be a date or a dateTime")


def check_own_body(body: object) -> None:
    """Raise ``UnsafeAutoEvent`` unless ``body`` is exactly a plain, marked, guest-free event."""
    if not isinstance(body, dict):
        raise UnsafeAutoEvent("event body must be an object")
    extra = set(body) - _ALLOWED_KEYS
    if extra:
        raise UnsafeAutoEvent(f"event field not allowed: {', '.join(sorted(extra))}")
    marker = body.get("extendedProperties")
    private = marker.get("private") if isinstance(marker, dict) else None
    value = private.get(MARKER_KEY) if isinstance(private, dict) else None
    if (
        not isinstance(value, str)
        or not _MARKER_RE.fullmatch(value)
        or marker != {"private": {MARKER_KEY: value}}
    ):
        raise UnsafeAutoEvent("event must carry exactly the automatic-event marker")
    for name in ("summary", "description"):
        if name in body and not isinstance(body[name], str):
            raise UnsafeAutoEvent(f"{name} must be a string")
    if not isinstance(body.get("summary"), str):
        raise UnsafeAutoEvent("summary is required")
    _check_time(body.get("start"), "start")
    _check_time(body.get("end"), "end")
    if "reminders" in body and body["reminders"] != {"useDefault": True}:
        raise UnsafeAutoEvent("reminders must use the calendar defaults")
    if "transparency" in body and body["transparency"] not in ("transparent", "opaque"):
        raise UnsafeAutoEvent("invalid transparency")


def _source_label(deadline: Deadline) -> str:
    if deadline.source == "classroom":
        return f"Google Classroom ({deadline.source_account})"
    return f"an email to {deadline.source_account}"


def build_event(deadline: Deadline, marker: str) -> dict[str, Any]:
    """The event for a deadline: a 30-minute block ending at the due time, or an all-day entry."""
    start: Any
    end: Any
    if isinstance(deadline.due, datetime):
        start, end = deadline.due - BLOCK, deadline.due
    else:
        start, end = deadline.due, deadline.due + timedelta(days=1)
    return {
        "summary": f"Due: {deadline.title}"[:SUMMARY_CHARS],
        "description": (
            f"Added automatically by PersonalAi from {_source_label(deadline)}. "
            "Undo it from the PersonalAi app."
        ),
        "start": time_field(start),
        "end": time_field(end),
        "transparency": "transparent",
        "reminders": {"useDefault": True},
        "extendedProperties": {"private": {MARKER_KEY: marker}},
    }


class AlertSink(Protocol):
    def add(
        self,
        kind: str,
        dedupe_key: str,
        title: str,
        body: str,
        target: dict[str, Any],
        actions: tuple[str, ...] = (),
    ) -> bool: ...


class AutoCalendar:
    def __init__(
        self,
        db: Database,
        deadlines: DeadlineStore,
        api_for: Callable[[str], OwnCalendarApi],
        calendar_account: str | None,
        clock: Clock,
        audit: AuditLog,
        alerts: AlertSink,
        enabled: bool,
        local_offset: int,
    ) -> None:
        self._db = db
        self._deadlines = deadlines
        self._api_for = api_for
        self._account = calendar_account
        self._clock = clock
        self._audit = audit
        self._alerts = alerts
        self._enabled = enabled
        self._offset = local_offset

    # --- adding -----------------------------------------------------------------------------

    def run(self) -> int:
        """Put due deadlines on the calendar; returns how many events were created."""
        if not self._enabled or self._account is None:
            return 0
        now = self._clock()
        used = self._db.query(
            "SELECT COUNT(*) AS n FROM auto_events WHERE created_at > ?",
            ((now - timedelta(hours=24)).isoformat(),),
        )[0]["n"]
        budget = min(MAX_PER_RUN, MAX_PER_DAY - used)
        if budget <= 0:
            return 0
        try:
            api = self._api_for(self._account)
        except Exception as exc:
            log.warning("auto calendar unavailable: %s", type(exc).__name__)
            return 0
        created = 0
        for deadline, marker, known in self._candidates(now)[:budget]:
            try:
                created += self._add(api, deadline, marker, known)
            except Exception as exc:  # one failing item must not stop the others
                log.warning("auto calendar item failed: %s", type(exc).__name__)
        log.info("auto calendar created %d events", created)
        return created

    def _candidates(self, now: datetime) -> list[tuple[Deadline, str, bool]]:
        """Active deadlines still ahead and not yet on the calendar, oldest first. ``known`` marks
        one whose row was written but whose event was not recorded (an interrupted run)."""
        rows = self._db.query(
            "SELECT d.id AS id, e.marker AS marker, e.deadline_id AS known "
            "FROM deadlines d LEFT JOIN auto_events e ON e.deadline_id = d.id "
            "WHERE d.status = 'active' AND (e.deadline_id IS NULL "
            "OR (e.event_id = '' AND e.undone_at IS NULL)) ORDER BY d.created_at, d.id"
        )
        found: list[tuple[Deadline, str, bool]] = []
        for row in rows:
            deadline = self._deadlines.get(row["id"])
            if deadline is None:
                continue
            start, end = due_span(deadline.due, self._offset)
            if end > now and start <= now + MAX_AHEAD:
                found.append(
                    (deadline, row["marker"] or secrets.token_hex(16), row["known"] is not None)
                )
        return found

    def _add(self, api: OwnCalendarApi, deadline: Deadline, marker: str, known: bool) -> int:
        assert self._account is not None  # noqa: S101 - checked by run
        if not known:
            self._db.execute(
                "INSERT INTO auto_events (deadline_id, calendar_account, event_id, marker, "
                "created_at) VALUES (?, ?, '', ?, ?)",
                (deadline.id, self._account, marker, self._clock().isoformat()),
            )
        existing = api.find_own(marker)
        if existing:  # the event was created before an interrupted run recorded it
            self._record_event(deadline.id, str(existing[0]["id"]))
            self._announce(deadline)
            return 0
        body = build_event(deadline, marker)
        check_own_body(body)
        event = api.insert_own_event(body)
        self._record_event(deadline.id, str(event["id"]))
        self._audit.record(
            "calendar_auto_add", actor="system:autocal", detail=f"deadline:{deadline.id}"
        )
        self._announce(deadline)
        return 1

    def _record_event(self, deadline_id: int, event_id: str) -> None:
        self._db.execute(
            "UPDATE auto_events SET event_id = ? WHERE deadline_id = ?", (event_id, deadline_id)
        )

    def _announce(self, deadline: Deadline) -> None:
        shown = (
            deadline.due.astimezone(local_tz(self._offset)).strftime("%a %d %b %H:%M")
            if isinstance(deadline.due, datetime)
            else deadline.due.strftime("%a %d %b")
        )
        self._alerts.add(
            "calendar_added",
            f"calendar_added:{deadline.id}",
            "Added to your calendar",
            f"{deadline.title} · {shown}",
            deadline_target(deadline),
            ("undo",),
        )

    # --- undoing ----------------------------------------------------------------------------

    def undo(self, deadline_id: int, device_id: str) -> str:
        """Delete an event this module created. One of ``undone``, ``not_found``, ``refused``."""
        rows = self._db.query(
            "SELECT calendar_account, event_id, marker FROM auto_events "
            "WHERE deadline_id = ? AND undone_at IS NULL AND event_id != ''",
            (deadline_id,),
        )
        if not rows:
            return "not_found"
        try:
            row = rows[0]
            self._api_for(row["calendar_account"]).delete_own(row["event_id"], row["marker"])
        except EventNotFound:
            pass  # already gone: the owner's wish is met
        except NotOwnEvent:
            return "refused"
        with self._db.transaction():
            self._db.execute(
                "UPDATE auto_events SET undone_at = ? WHERE deadline_id = ?",
                (self._clock().isoformat(), deadline_id),
            )
            self._db.execute("UPDATE deadlines SET status = 'undone' WHERE id = ?", (deadline_id,))
            self._audit.record(
                "calendar_auto_undo", actor=f"device:{device_id}", detail=f"deadline:{deadline_id}"
            )
        return "undone"
