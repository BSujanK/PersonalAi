"""Deadlines found in mail and Classroom, stored encrypted. Nothing here writes to a calendar."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from agent.connectors.classroom import ClassroomApi, due_instant, due_of
from agent.connectors.gmail import MailMessage
from agent.core.clock import Clock
from agent.core.llm import LLMClient
from agent.core.redact import RedactionMap, Redactor
from agent.core.textutil import one_line
from agent.mail.store import MailStore
from agent.proactive.extract import ExtractionFailed, Found, extract_with_llm_strict, scan_rules
from agent.proactive.mailfilter import is_bulk_mail, is_trusted_sender
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.sync_status import CLASSROOM, record_scan

log = logging.getLogger(__name__)

TITLE_CHARS = 150
SKIPPED_LABELS = frozenset({"SPAM", "TRASH", "SENT", "DRAFT"})
SKIPPED_CATEGORIES = frozenset({"promo", "spam"})
MAIL_SCAN_DAYS = 30  # how far back the catch-up scan looks at stored mail
MAIL_SCAN_LIMIT = 200  # messages one catch-up run looks at, so a run stays short
MAIL_SCAN_MAX_FAILURES = 3  # consecutive model failures after which a run stops (model is down)


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


def deadline_target(item: Deadline) -> dict[str, Any]:
    """Where an alert about ``item`` leads in the app: ids and the source account, never text.
    A Classroom deadline's course id is the middle part of its ``account/course/work`` key."""
    target: dict[str, Any] = {
        "type": "deadline",
        "deadline_id": item.id,
        "source": item.source,
        "account": item.source_account,
    }
    if item.source == "mail":
        target["message_id"] = item.source_id
    elif item.source == "classroom":
        parts = item.source_key.split("/")
        if len(parts) == 3:
            target["course_id"] = parts[1]
    return target


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

    def calendar_event(self, deadline_id: int) -> tuple[str, str] | None:
        """``(calendar_account, event_id)`` of the live auto-added event for a deadline, or None
        when none was added or it was undone (same condition as ``calendar_added_ids``)."""
        rows = self._db.query(
            "SELECT calendar_account, event_id FROM auto_events WHERE deadline_id = ? "
            "AND undone_at IS NULL AND event_id != ''",
            (deadline_id,),
        )
        return (rows[0]["calendar_account"], rows[0]["event_id"]) if rows else None


@dataclass(frozen=True)
class MailScanResult:
    """Counts only; a catch-up run never reports what a message said."""

    scanned: int  # messages handled and recorded as scanned
    failed: int  # messages left for the next run because the model could not be used
    added: int  # new deadlines stored


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
        vip_senders: frozenset[str],
        college_domains: frozenset[str],
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
        self._vip = vip_senders
        self._college = college_domains

    def list_upcoming(self, days: int) -> list[Deadline]:
        return self.store.upcoming(days, self._offset)

    # --- mail -------------------------------------------------------------------------------

    def on_new_mail(self, msg: MailMessage) -> None:
        """The MailSync hook: runs after classification, so the stored category is known."""
        if self._mail is None:
            return
        stored = self._mail.get(msg.account, msg.id)
        if stored is None:
            return
        try:
            added = self._scan_mail(
                msg.account,
                msg.id,
                msg.from_addr,
                msg.subject,
                msg.body,
                msg.label_ids,
                msg.list_unsubscribe,
                stored.category,
                msg.internal_date,
                self._horizon,
            )
        except ExtractionFailed:
            return  # left unscanned: the catch-up scan tries it again
        if added is not None:
            self._mail.mark_deadline_scanned(msg.account, msg.id)

    def scan_stored_mail(
        self, *, days: int = MAIL_SCAN_DAYS, limit: int = MAIL_SCAN_LIMIT
    ) -> MailScanResult:
        """Catch up on stored mail of the last ``days`` days the deadline scan has not seen.

        Uses the same extraction as ``on_new_mail`` (rules, then the local model on redacted
        text). A message is recorded as scanned only once extraction worked for it, so a model
        failure leaves it for the next run; the run stops after a few failures in a row.
        """
        mail = self._mail
        if mail is None:
            return MailScanResult(0, 0, 0)
        since = self._clock() - timedelta(days=days)
        scanned = failed = added = streak = 0
        for stored in mail.unscanned_for_deadlines(int(since.timestamp() * 1000), limit):
            try:
                new = self._scan_mail(
                    stored.account,
                    stored.id,
                    stored.from_addr,
                    stored.subject,
                    stored.body,
                    stored.label_ids,
                    stored.list_unsubscribe,
                    stored.category,
                    stored.internal_date,
                    timedelta(days=days),
                )
            except ExtractionFailed:
                failed += 1
                streak += 1
                if streak >= MAIL_SCAN_MAX_FAILURES:
                    break
                continue
            streak = 0
            if new is not None:
                mail.mark_deadline_scanned(stored.account, stored.id)
                scanned += 1
                added += new
        log.info("mail deadline scan: scanned=%d failed=%d added=%d", scanned, failed, added)
        return MailScanResult(scanned, failed, added)

    def _scan_mail(
        self,
        account: str,
        message_id: str,
        from_addr: str,
        subject: str,
        body: str,
        label_ids: Sequence[str],
        list_unsubscribe: bool,
        category: str | None,
        internal_date: int,
        max_age: timedelta,
    ) -> int | None:
        """Extract and store the deadlines of one mail.

        Returns the number of new deadlines, or ``None`` when the mail was not looked at because
        it is older than ``max_age``. Mail the rules skip (spam, promo, sent, and newsletters from
        senders that are not trusted) counts as looked at.
        Raises ``ExtractionFailed`` when the local model was needed but could not be used.
        """
        if SKIPPED_LABELS & set(label_ids) or category in SKIPPED_CATEGORIES:
            return 0
        if not is_trusted_sender(from_addr, self._vip, self._college):
            reason = is_bulk_mail(from_addr, subject, body, label_ids, list_unsubscribe)
            if reason is not None:
                log.info("deadline scan skipped bulk mail: %s", reason)
                return 0
        received = datetime.fromtimestamp(internal_date / 1000, UTC)
        if self._clock() - received > max_age:
            return None
        redacted = self._redactor.redact(f"{subject}\n{body}", RedactionMap()).text
        scan = scan_rules(redacted, received, self._offset)
        found: Sequence[Found] = scan.found
        if not found and scan.trigger and not scan.dated and self._llm is not None:
            found = extract_with_llm_strict(
                self._llm, self._redactor, subject, body, received, self._offset
            )
        title = one_line(subject, TITLE_CHARS, "(no subject)")
        added = 0
        for item in found:
            if self.store.insert(
                source="mail",
                source_key=f"{account}/{message_id}/{item.due.isoformat()[:10]}",
                source_account=account,
                source_id=message_id,
                kind=item.kind,
                title=title,
                due=item.due,
                found_by=item.found_by,
            ):
                added += 1
        if found:
            log.info("deadlines found in one mail: %d", len(found))
        return added

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
