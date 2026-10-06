"""Deadlines found in mail and Classroom, stored encrypted. Nothing here writes to a calendar."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

from agent.connectors.classroom import ClassroomApi, due_instant, due_of
from agent.connectors.gmail import MailMessage
from agent.core.clock import Clock
from agent.core.llm import LLMClient
from agent.core.redact import RedactionMap, Redactor
from agent.core.textutil import one_line
from agent.mail.store import MailStore
from agent.proactive.extract import Found, extract_with_llm, scan_rules
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.sync_status import CLASSROOM, record_scan

log = logging.getLogger(__name__)

TITLE_CHARS = 150
SKIPPED_LABELS = frozenset({"SPAM", "TRASH", "SENT", "DRAFT"})
SKIPPED_CATEGORIES = frozenset({"promo", "spam"})


def local_tz(offset_minutes: int) -> timezone:
    return timezone(timedelta(minutes=offset_minutes))


def due_span(due: date | datetime, offset_minutes: int) -> tuple[datetime, datetime]:
    """When a due value starts and ends: an instant for a datetime, the local day for a date."""
    if isinstance(due, datetime):
        return due, due
    start = datetime.combine(due, time.min, tzinfo=local_tz(offset_minutes))
    return start, start + timedelta(days=1)


def parse_due(text: str) -> date | datetime:
    return datetime.fromisoformat(text) if "T" in text else date.fromisoformat(text)


@dataclass(frozen=True)
class Deadline:
    id: int
    source: str
    source_key: str
    source_account: str
    source_id: str
    kind: str
    title: str
    due: date | datetime
    found_by: str
    created_at: str
    status: str


def _aad(source: str, source_key: str) -> str:
    return f"deadlines.title:{source}/{source_key}"


class DeadlineStore:
    def __init__(self, db: Database, cipher: FieldCipher, clock: Clock) -> None:
        self._db = db
        self._cipher = cipher
        self._clock = clock

    def _hydrate(self, row: sqlite3.Row) -> Deadline:
        return Deadline(
            id=row["id"],
            source=row["source"],
            source_key=row["source_key"],
            source_account=row["source_account"],
            source_id=row["source_id"],
            kind=row["kind"],
            title=self._cipher.decrypt_str(
                row["title_enc"], _aad(row["source"], row["source_key"])
            ),
            due=parse_due(row["due"]),
            found_by=row["found_by"],
            created_at=row["created_at"],
            status=row["status"],
        )

    def insert(
        self,
        *,
        source: str,
        source_key: str,
        source_account: str,
        source_id: str,
        kind: str,
        title: str,
        due: date | datetime,
        found_by: str,
    ) -> bool:
        """Store a deadline once per ``(source, source_key)``. True when it was new."""
        cur = self._db.execute(
            "INSERT INTO deadlines (source, source_key, source_account, source_id, kind, "
            "title_enc, due, found_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (source, source_key) DO NOTHING",
            (
                source,
                source_key,
                source_account,
                source_id,
                kind,
                self._cipher.encrypt(title, _aad(source, source_key)),
                due.isoformat(),
                found_by,
                self._clock().isoformat(),
            ),
        )
        return cur.rowcount > 0

    def update_due_if_not_on_calendar(
        self, source: str, source_key: str, due: date | datetime
    ) -> bool:
        """Move a deadline's due date, but only while nothing was put on a calendar for it."""
        cur = self._db.execute(
            "UPDATE deadlines SET due = ? WHERE source = ? AND source_key = ? AND due != ? "
            "AND id NOT IN (SELECT deadline_id FROM auto_events)",
            (due.isoformat(), source, source_key, due.isoformat()),
        )
        return cur.rowcount > 0

    def get(self, deadline_id: int) -> Deadline | None:
        rows = self._db.query("SELECT * FROM deadlines WHERE id = ?", (deadline_id,))
        return self._hydrate(rows[0]) if rows else None

    def upcoming(
        self,
        days: int,
        offset_minutes: int,
        *,
        statuses: Sequence[str] = ("active",),
        now: datetime | None = None,
    ) -> list[Deadline]:
        """Deadlines whose due moment is still ahead and starts within ``days``, soonest first."""
        moment = now if now is not None else self._clock()
        local = local_tz(offset_minutes)
        first = (moment.astimezone(local) - timedelta(days=1)).date().isoformat()
        last = (moment.astimezone(local) + timedelta(days=days + 1)).date().isoformat()
        marks = ",".join("?" for _ in statuses)
        rows = self._db.query(
            f"SELECT * FROM deadlines WHERE status IN ({marks}) "  # noqa: S608 - placeholders only
            "AND substr(due, 1, 10) >= ? AND substr(due, 1, 10) <= ?",
            (*statuses, first, last),
        )
        found: list[Deadline] = []
        for row in rows:
            item = self._hydrate(row)
            start, end = due_span(item.due, offset_minutes)
            if end > moment and start <= moment + timedelta(days=days):
                found.append(item)
        found.sort(key=lambda d: (due_span(d.due, offset_minutes)[0], d.id))
        return found

    def calendar_added_ids(self, ids: Sequence[int]) -> set[int]:
        if not ids:
            return set()
        marks = ",".join("?" for _ in ids)
        rows = self._db.query(
            f"SELECT deadline_id FROM auto_events WHERE deadline_id IN ({marks}) "  # noqa: S608
            "AND undone_at IS NULL AND event_id != ''",
            tuple(ids),
        )
        return {row["deadline_id"] for row in rows}


class DeadlineCollector:
    """Finds deadlines in new mail (rules, then the local model) and in Classroom."""

    def __init__(
        self,
        store: DeadlineStore,
        *,
        db: Database,
        mail_store: MailStore | None,
        redactor: Redactor,
        llm: LLMClient | None,
        classroom_api_for: Callable[[str], ClassroomApi] | None,
        classroom_accounts: Sequence[str],
        clock: Clock,
        horizon_days: int,
        offset_minutes: int,
    ) -> None:
        self.store = store
        self._mail = mail_store
        self._redactor = redactor
        self._llm = llm
        self._classroom_api_for = classroom_api_for
        self._classroom_accounts = classroom_accounts
        self._clock = clock
        self._horizon = timedelta(days=horizon_days)
        self._offset = offset_minutes
        self._db = db

    def list_upcoming(self, days: int) -> list[Deadline]:
        return self.store.upcoming(days, self._offset)

    # --- mail -------------------------------------------------------------------------------

    def on_new_mail(self, msg: MailMessage) -> None:
        """The MailSync hook: runs after classification, so the stored category is known."""
        if self._mail is None or SKIPPED_LABELS & set(msg.label_ids):
            return
        stored = self._mail.get(msg.account, msg.id)
        if stored is None or stored.category in SKIPPED_CATEGORIES:
            return
        now = self._clock()
        received = datetime.fromtimestamp(msg.internal_date / 1000, UTC)
        if now - received > self._horizon:
            return
        redacted = self._redactor.redact(f"{msg.subject}\n{msg.body}", RedactionMap()).text
        scan = scan_rules(redacted, received, self._offset)
        found: Sequence[Found] = scan.found
        if not found and scan.trigger and not scan.dated and self._llm is not None:
            found = extract_with_llm(
                self._llm, self._redactor, msg.subject, msg.body, received, self._offset
            )
        title = one_line(msg.subject, TITLE_CHARS, "(no subject)")
        for item in found:
            self.store.insert(
                source="mail",
                source_key=f"{msg.account}/{msg.id}/{item.due.isoformat()[:10]}",
                source_account=msg.account,
                source_id=msg.id,
                kind=item.kind,
                title=title,
                due=item.due,
                found_by=item.found_by,
            )
        if found:
            log.info("deadlines found in one new mail: %d", len(found))

    # --- Classroom --------------------------------------------------------------------------

    def scan_classroom(self) -> int:
        """Store upcoming Classroom due dates; returns how many deadlines were new."""
        api_for = self._classroom_api_for
        if api_for is None or not self._classroom_accounts:
            return 0
        added = succeeded = 0
        failures: list[str] = []
        for account in self._classroom_accounts:
            try:
                added += self._scan_account(api_for(account), account)
            except Exception as exc:  # one broken account must not stop the others
                log.warning("deadline scan failed for an account: %s", type(exc).__name__)
                failures.append(type(exc).__name__)
            else:
                succeeded += 1
        record_scan(self._db, CLASSROOM, self._clock, succeeded=succeeded, failures=failures)
        log.info("classroom deadline scan added %d deadlines", added)
        return added

    def _scan_account(self, api: ClassroomApi, account: str) -> int:
        now = self._clock()
        added = 0
        for course in api.list_courses():
            course_id = course.get("id")
            if not isinstance(course_id, str):
                continue
            course_name = one_line(course.get("name"), 200, "Course")
            for work in api.list_coursework(course_id):
                work_id = work.get("id")
                due = due_of(work)
                if not isinstance(work_id, str) or due is None:
                    continue
                if not now < due_instant(due) <= now + self._horizon:
                    continue
                key = f"{account}/{course_id}/{work_id}"
                title = one_line(
                    f"{one_line(work.get('title'), 200, 'Assignment')} ({course_name})", TITLE_CHARS
                )
                if self.store.insert(
                    source="classroom",
                    source_key=key,
                    source_account=account,
                    source_id=work_id,
                    kind="submission",
                    title=title,
                    due=due,
                    found_by="classroom",
                ):
                    added += 1
                else:
                    self.store.update_due_if_not_on_calendar("classroom", key, due)
        return added
