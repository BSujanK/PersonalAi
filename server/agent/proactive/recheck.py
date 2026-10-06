"""One-off clean-up of mail deadlines the newsletter filter and the proximity rule now reject.

``find_rejected`` only reads. ``apply_rejections`` removes the calendar event of a rejected
deadline through ``AutoCalendar.undo`` (so every safety check of an undo still applies) or, for
one that never reached the calendar, marks it ``undone`` so it is never added. It never touches
Classroom deadlines. Reason codes and ids are the only things logged or audited.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from agent.config import Settings
from agent.core.audit import AuditLog
from agent.core.redact import RedactionMap, Redactor
from agent.mail.store import MailStore, StoredMail
from agent.proactive.autocal import AutoCalendar
from agent.proactive.deadlines import Deadline, DeadlineStore
from agent.proactive.extract import scan_rules
from agent.proactive.mailfilter import is_bulk_mail, is_trusted_sender
from agent.store.db import Database

log = logging.getLogger(__name__)

RULE_NO_LONGER_MATCHES = "rule_no_longer_matches"
DEFAULT_ACTOR = "cli:recheck"


@dataclass(frozen=True)
class Rejected:
    deadline_id: int
    kind: str
    due: date | datetime
    account: str
    title: str
    on_calendar: bool
    reason: str


@dataclass(frozen=True)
class RecheckCounts:
    undone: int  # calendar events removed
    dismissed: int  # deadlines that were not on the calendar, now never added
    refused: int  # the event was not one the agent created: nothing was changed
    failed: int


def _day(due: date | datetime) -> date:
    return due.date() if isinstance(due, datetime) else due


def _reason(
    deadline: Deadline,
    mail: StoredMail,
    settings: Settings,
    redactor: Redactor,
    offset_minutes: int,
) -> str | None:
    vip = frozenset(addr.lower() for addr in settings.vip_senders)
    college = frozenset(domain.lower() for domain in settings.college_domains)
    if not is_trusted_sender(mail.from_addr, vip, college):
        bulk = is_bulk_mail(
            mail.from_addr, mail.subject, mail.body, mail.label_ids, mail.list_unsubscribe
        )
        if bulk is not None:
            return f"bulk_mail:{bulk}"
    if deadline.found_by == "rule":
        received = datetime.fromtimestamp(mail.internal_date / 1000, UTC)
        redacted = redactor.redact(f"{mail.subject}\n{mail.body}", RedactionMap()).text
        scan = scan_rules(redacted, received, offset_minutes)
        if _day(deadline.due) not in {_day(found.due) for found in scan.found}:
            return RULE_NO_LONGER_MATCHES
    return None


def find_rejected(
    db: Database,
    deadline_store: DeadlineStore,
    mail_store: MailStore,
    settings: Settings,
    offset_minutes: int,
) -> list[Rejected]:
    """Active mail deadlines that today's rules would not have stored. Read-only."""
    redactor = Redactor(settings.redaction_emails)
    ids = [
        row["id"]
        for row in db.query(
            "SELECT id FROM deadlines WHERE source = 'mail' AND status = 'active' ORDER BY id"
        )
    ]
    deadlines = [d for d in (deadline_store.get(i) for i in ids) if d is not None]
    on_calendar = deadline_store.calendar_added_ids([d.id for d in deadlines])
    rejected: list[Rejected] = []
    for deadline in deadlines:
        stored = mail_store.get(deadline.source_account, deadline.source_id)
        if stored is None:
            continue
        reason = _reason(deadline, stored, settings, redactor, offset_minutes)
        if reason is not None:
            rejected.append(
                Rejected(
                    deadline.id,
                    deadline.kind,
                    deadline.due,
                    deadline.source_account,
                    deadline.title,
                    deadline.id in on_calendar,
                    reason,
                )
            )
    return rejected


def apply_rejections(
    rejected: Sequence[Rejected],
    autocal: AutoCalendar,
    deadline_db: Database,
    audit: AuditLog,
    actor: str = DEFAULT_ACTOR,
) -> RecheckCounts:
    """Undo or dismiss each rejected deadline; one failure never stops the others."""
    undone = dismissed = refused = failed = 0
    for item in rejected:
        try:
            if item.on_calendar:
                outcome = autocal.undo(item.deadline_id, actor)
                if outcome == "undone":
                    undone += 1
                elif outcome == "refused":
                    refused += 1
                else:
                    failed += 1
            elif _dismiss(deadline_db, audit, item.deadline_id, actor):
                dismissed += 1
            else:
                failed += 1
        except Exception as exc:
            log.warning("deadline recheck item failed: %s", type(exc).__name__)
            failed += 1
    log.info(
        "deadline recheck: undone=%d dismissed=%d refused=%d failed=%d",
        undone,
        dismissed,
        refused,
        failed,
    )
    return RecheckCounts(undone, dismissed, refused, failed)


def _dismiss(db: Database, audit: AuditLog, deadline_id: int, actor: str) -> bool:
    with db.transaction():
        cur = db.execute(
            "UPDATE deadlines SET status = 'undone' WHERE id = ? AND status = 'active'",
            (deadline_id,),
        )
        if cur.rowcount == 0:
            return False
        audit.record("deadline_dismissed", actor=actor, detail=f"deadline:{deadline_id}")
    return True
