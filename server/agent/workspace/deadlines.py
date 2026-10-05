"""Classroom deadlines proposed as calendar events. Every event still needs approval."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from agent.connectors.classroom import ClassroomApi, due_instant, due_of
from agent.connectors.gcal import CalendarApi
from agent.core.approvals import ApprovalEngine
from agent.core.clock import Clock
from agent.core.policy import MAX_PENDING_ACTIONS
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.store.db import Database
from agent.store.models import ActionStatus
from agent.store.sync_status import CLASSROOM, record_failure, record_scan
from agent.workspace.calendar_tools import (
    NO_GUESTS,
    check_account,
    check_text,
    describe_when,
    parse_when,
    time_field,
)

log = logging.getLogger(__name__)

TOOL_NAME = "calendar_add_deadline"
PROPERTY_KEY = "personalai_coursework"
DESCRIPTION = "Added from Google Classroom."
BLOCK = timedelta(minutes=30)
RETRY_AFTER = timedelta(hours=24)
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ACCOUNT_RE = re.compile(r"[^\s/]{1,254}")


@dataclass(frozen=True)
class _Deadline:
    calendar_account: str
    key: str
    summary: str
    start: date | datetime
    end: date | datetime

    def body(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "start": time_field(self.start),
            "end": time_field(self.end),
            "description": DESCRIPTION,
            "extendedProperties": {"private": {PROPERTY_KEY: self.key}},
        }


def _parse(args: dict[str, Any], calendar_accounts: Sequence[str]) -> _Deadline:
    calendar_account = check_account(args.get("calendar_account"), calendar_accounts)
    classroom_account = args.get("classroom_account")
    if not isinstance(classroom_account, str) or not _ACCOUNT_RE.fullmatch(classroom_account):
        raise ValueError("invalid classroom_account")
    ids: list[str] = []
    for name in ("course_id", "coursework_id"):
        value = args.get(name)
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise ValueError(f"invalid {name}")
        ids.append(value)
    title = check_text(args.get("title"), "title", limit=200, minimum=1, one_line=True)
    course = check_text(args.get("course"), "course", limit=200, minimum=1, one_line=True)
    due = parse_when(args.get("due"), "due")
    start: date | datetime
    end: date | datetime
    if isinstance(due, datetime):
        start, end = due - BLOCK, due
    else:
        start, end = due, due + timedelta(days=1)
    return _Deadline(
        calendar_account,
        "/".join([classroom_account, *ids]),
        f"Due: {title} ({course})",
        start,
        end,
    )


def register_deadline_tool(
    registry: ToolRegistry,
    calendar_api_for: Callable[[str], CalendarApi],
    calendar_accounts: Sequence[str],
) -> None:
    def preview(args: dict[str, Any]) -> str:
        item = _parse(args, calendar_accounts)
        return "\n".join(
            [
                f"Add deadline to the calendar of {item.calendar_account}",
                f"Title: {item.summary}",
                f"When: {describe_when(item.start, item.end)}",
                f"Description: {DESCRIPTION}",
                NO_GUESTS,
            ]
        )

    def run(args: dict[str, Any]) -> Any:
        item = _parse(args, calendar_accounts)
        api = calendar_api_for(item.calendar_account)
        if api.find_private(PROPERTY_KEY, item.key):
            return {"ok": 0, "duplicate": True}
        created = api.insert_event(item.body())
        return {"ok": 1, "id": created["id"]}

    registry.register(
        Tool(
            name=TOOL_NAME,
            description=(
                "Put a Classroom assignment's due date on the owner's calendar (no guests are "
                "invited; requires the owner's approval). Use it after classroom_coursework "
                "found the assignment, copying that item's values: classroom_account is its "
                "account, plus its course_id, coursework_id (its id), title, course (its course "
                "name) and due. calendar_account is the calendar to add it to, one of the "
                "calendar accounts. For anything that did not come from Classroom, use "
                "calendar_create_event instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "calendar_account": {
                        "type": "string",
                        "description": "The calendar account the event is added to.",
                    },
                    "classroom_account": {
                        "type": "string",
                        "description": "The account field of the classroom_coursework item.",
                    },
                    "course_id": {
                        "type": "string",
                        "description": "The course_id field of the classroom_coursework item.",
                    },
                    "coursework_id": {
                        "type": "string",
                        "description": "The id field of the classroom_coursework item.",
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "The assignment title, copied from the item.",
                    },
                    "course": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "The course name, copied from the item's course field.",
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "The due field of the item, unchanged: an ISO datetime with offset, "
                            "or an ISO date for an all-day deadline."
                        ),
                    },
                },
                "required": [
                    "calendar_account",
                    "classroom_account",
                    "course_id",
                    "coursework_id",
                    "title",
                    "course",
                    "due",
                ],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=run,
            preview=preview,
        )
    )


@dataclass
class _Scan:
    pending: int
    proposed: int = 0
    scanned: int = 0  # accounts whose courses and coursework were read successfully
    failures: list[str] = field(default_factory=list)  # exception type name per failed account


@dataclass(frozen=True)
class ScanReport:
    """What one pass did. ``scanned`` counts accounts read successfully, ``failures`` the rest."""

    proposed: int
    scanned: int
    failures: tuple[str, ...]
    accounts: int


def _line(text: Any, limit: int, default: str) -> str:
    collapsed = " ".join(text.split())[:limit] if isinstance(text, str) else ""
    return collapsed or default


class DeadlineProposer:
    """Proposes one calendar event per upcoming Classroom deadline, at most once per due date."""

    def __init__(
        self,
        db: Database,
        approvals: ApprovalEngine,
        classroom_api_for: Callable[[str], ClassroomApi],
        classroom_accounts: Sequence[str],
        calendar_account: str | None,
        clock: Clock,
        horizon_days: int,
    ) -> None:
        self._db = db
        self._approvals = approvals
        self._api_for = classroom_api_for
        self._accounts = classroom_accounts
        self._calendar_account = calendar_account
        self._clock = clock
        self._horizon = timedelta(days=horizon_days)

    def run(self) -> int:
        """Propose new deadlines; returns how many proposals were created."""
        return self.scan().proposed

    def scan(self) -> ScanReport:
        """Like :meth:`run`, but also says which accounts could be read (for sync status)."""
        if self._calendar_account is None:
            return ScanReport(0, 0, (), len(self._accounts))
        scan = _Scan(self._approvals.pending_count())
        for account in self._accounts:
            if self._full(scan):
                break
            try:
                self._scan_account(account, scan)
            except Exception as exc:  # one broken account must not stop the others
                log.warning("deadline scan failed for an account: %s", type(exc).__name__)
                scan.failures.append(type(exc).__name__)
            else:
                scan.scanned += 1
        log.info("deadline scan proposed %d actions", scan.proposed)
        return ScanReport(scan.proposed, scan.scanned, tuple(scan.failures), len(self._accounts))

    def run_and_record(self) -> int:
        """The scheduled job: scan, then record Classroom as OK only if an account was read."""
        report = self.scan()
        if report.scanned == 0 and not report.failures and report.accounts:
            # Nothing was read and nothing failed: too many approvals were already pending.
            reason = "scan skipped: too many approvals are pending"
            record_failure(self._db, CLASSROOM, self._clock, reason)
        else:
            record_scan(
                self._db, CLASSROOM, self._clock, succeeded=report.scanned, failures=report.failures
            )
        return report.proposed

    @staticmethod
    def _full(scan: _Scan) -> bool:
        return scan.pending >= MAX_PENDING_ACTIONS // 2

    def _scan_account(self, account: str, scan: _Scan) -> None:
        api = self._api_for(account)
        now = self._clock()
        for course in api.list_courses():
            course_id = course.get("id")
            if not isinstance(course_id, str):
                continue
            course_name = _line(course.get("name"), 200, "Course")
            for work in api.list_coursework(course_id):
                if self._full(scan):
                    return
                due = due_of(work)
                if due is None or not now < due_instant(due) <= now + self._horizon:
                    continue
                self._consider(account, course_id, course_name, work, due.isoformat(), scan)

    def _consider(
        self,
        account: str,
        course_id: str,
        course_name: str,
        work: dict[str, Any],
        due: str,
        scan: _Scan,
    ) -> None:
        coursework_id = work.get("id")
        if not isinstance(coursework_id, str) or not self._should_propose(
            account, course_id, coursework_id, due
        ):
            return
        args = {
            "calendar_account": self._calendar_account,
            "classroom_account": account,
            "course_id": course_id,
            "coursework_id": coursework_id,
            "title": _line(work.get("title"), 200, "Assignment"),
            "course": course_name,
            "due": due,
        }
        try:
            action = self._approvals.propose(TOOL_NAME, args, None)
        except ValueError:  # an id or value the tool rejects; skip just this item
            return
        with self._db.transaction():
            self._db.execute(
                "INSERT INTO deadline_proposals (classroom_account, course_id, coursework_id, "
                "due_at, action_id, proposed_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (classroom_account, course_id, coursework_id) DO UPDATE SET "
                "due_at = excluded.due_at, action_id = excluded.action_id, "
                "proposed_at = excluded.proposed_at",
                (account, course_id, coursework_id, due, action.id, self._clock().isoformat()),
            )
        scan.pending += 1
        scan.proposed += 1

    def _should_propose(self, account: str, course_id: str, coursework_id: str, due: str) -> bool:
        rows = self._db.query(
            "SELECT due_at, action_id, proposed_at FROM deadline_proposals "
            "WHERE classroom_account = ? AND course_id = ? AND coursework_id = ?",
            (account, course_id, coursework_id),
        )
        if not rows:
            return True
        row = rows[0]
        if row["due_at"] != due:
            return True
        action = self._approvals.get(row["action_id"])
        retryable = action is None or action.status in (ActionStatus.EXPIRED, ActionStatus.FAILED)
        return (
            retryable and self._clock() - datetime.fromisoformat(row["proposed_at"]) > RETRY_AFTER
        )
