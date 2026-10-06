"""Alerts for the phone: a pull feed (``GET /notifications``) the app turns into local
notifications. Content is encrypted at rest and travels only over Tailscale to the paired phone;
push notifications stay content-free. Logs carry ids and counts only."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from agent.connectors.gmail import MailMessage
from agent.core.clock import Clock
from agent.core.textutil import one_line
from agent.core.tools import ToolKind, ToolRegistry
from agent.mail.store import MailStore
from agent.proactive.autocal import AutoCalendar
from agent.proactive.deadlines import Deadline, DeadlineCollector, due_span, local_tz
from agent.store.crypto import FieldCipher
from agent.store.db import Database

log = logging.getLogger(__name__)

KINDS = ("important_mail", "deadline", "briefing", "calendar_added")
TITLE_CHARS = 80
BODY_CHARS = 300
RETENTION = timedelta(days=14)
MAX_MAIL_ALERTS_PER_PASS = 5
MAIL_ALERT_MAX_AGE = timedelta(hours=6)
BRIEFING_GRACE = timedelta(hours=3)
BRIEFING_DEADLINE_DAYS = 7
DAY_BEFORE_ALERT_HOURS = 15  # all-day deadlines: from 09:00 the day before
SKIPPED_LABELS = frozenset({"SPAM", "TRASH", "SENT", "DRAFT"})

Target = dict[str, Any]


@dataclass(frozen=True)
class Alert:
    id: int
    kind: str
    created_at: str
    title: str
    body: str
    target: Target
    actions: tuple[str, ...]


@dataclass(frozen=True)
class AlertSettings:
    important_mail: bool
    deadlines: bool
    briefing: bool
    briefing_time: str


class AlertStore:
    def __init__(
        self, db: Database, cipher: FieldCipher, clock: Clock, default_briefing_time: str
    ) -> None:
        self._db = db
        self._cipher = cipher
        self._clock = clock
        self._default_briefing_time = default_briefing_time

    def add(
        self,
        kind: str,
        dedupe_key: str,
        title: str,
        body: str,
        target: Target,
        actions: tuple[str, ...] = (),
    ) -> bool:
        """Store an alert once per ``dedupe_key``. True when it was new."""
        if kind not in KINDS:
            raise ValueError("unknown alert kind")
        content = json.dumps(
            {
                "title": one_line(title, TITLE_CHARS, "PersonalAi"),
                "body": one_line(body, BODY_CHARS),
                "target": target,
                "actions": list(actions),
            }
        )
        cur = self._db.execute(
            "INSERT OR IGNORE INTO alerts (kind, dedupe_key, created_at, content_enc) "
            "VALUES (?, ?, ?, ?)",
            (
                kind,
                dedupe_key,
                self._clock().isoformat(),
                self._cipher.encrypt(content, f"alerts.content:{dedupe_key}"),
            ),
        )
        return cur.rowcount > 0

    def exists(self, dedupe_key: str) -> bool:
        return bool(self._db.query("SELECT 1 FROM alerts WHERE dedupe_key = ?", (dedupe_key,)))

    def since(self, after_id: int, limit: int) -> list[Alert]:
        rows = self._db.query(
            "SELECT * FROM alerts WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit)
        )
        alerts: list[Alert] = []
        for row in rows:
            content = json.loads(
                self._cipher.decrypt_str(row["content_enc"], f"alerts.content:{row['dedupe_key']}")
            )
            alerts.append(
                Alert(
                    id=row["id"],
                    kind=row["kind"],
                    created_at=row["created_at"],
                    title=content["title"],
                    body=content["body"],
                    target=content["target"],
                    actions=tuple(content["actions"]),
                )
            )
        return alerts

    def latest_id(self) -> int:
        """The newest id ever issued, so it never goes backwards when old alerts are pruned."""
        rows = self._db.query("SELECT seq FROM sqlite_sequence WHERE name = 'alerts'")
        return int(rows[0]["seq"]) if rows else 0

    def prune(self, older_than: timedelta = RETENTION) -> int:
        cur = self._db.execute(
            "DELETE FROM alerts WHERE created_at < ?", ((self._clock() - older_than).isoformat(),)
        )
        return cur.rowcount

    def settings(self) -> AlertSettings:
        with self._db.transaction():
            self._db.execute(
                "INSERT OR IGNORE INTO alert_settings (id, briefing_time, updated_at) "
                "VALUES (1, ?, ?)",
                (self._default_briefing_time, self._clock().isoformat()),
            )
            row = self._db.query("SELECT * FROM alert_settings WHERE id = 1")[0]
        return AlertSettings(
            bool(row["important_mail"]),
            bool(row["deadlines"]),
            bool(row["briefing"]),
            row["briefing_time"],
        )

    def save_settings(self, new: AlertSettings) -> AlertSettings:
        self._db.execute(
            "INSERT INTO alert_settings (id, important_mail, deadlines, briefing, briefing_time, "
            "updated_at) VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET "
            "important_mail = excluded.important_mail, deadlines = excluded.deadlines, "
            "briefing = excluded.briefing, briefing_time = excluded.briefing_time, "
            "updated_at = excluded.updated_at",
            (
                int(new.important_mail),
                int(new.deadlines),
                int(new.briefing),
                new.briefing_time,
                self._clock().isoformat(),
            ),
        )
        return self.settings()


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _shown(due: date | datetime, offset_minutes: int) -> str:
    if isinstance(due, datetime):
        return due.astimezone(local_tz(offset_minutes)).strftime("%a %d %b %H:%M")
    return due.strftime("%a %d %b")


def deadline_body(item: Deadline, offset_minutes: int) -> str:
    return f"{item.kind.capitalize()} · {_shown(item.due, offset_minutes)}"


def _deadline_stages(item: Deadline, now: datetime, offset_minutes: int) -> list[str]:
    """The reminder stages whose window ``now`` falls in."""
    start, _ = due_span(item.due, offset_minutes)
    if isinstance(item.due, datetime):
        windows = {
            "1d": (start - timedelta(hours=24), start - timedelta(hours=2)),
            "2h": (start - timedelta(hours=2), start),
        }
    else:
        windows = {"1d": (start - timedelta(hours=DAY_BEFORE_ALERT_HOURS), start)}
    return [stage for stage, (low, high) in windows.items() if low <= now < high]


_STAGE_TITLES = {"1d": "Due tomorrow", "2h": "Due in 2 hours"}


class AlertJob:
    """The scheduled pass: auto-add deadlines to the calendar, then raise due-soon alerts and the
    morning briefing, then forget old alerts. Each step is isolated from the others."""

    def __init__(
        self,
        alerts: AlertStore,
        deadlines: DeadlineCollector,
        autocal: AutoCalendar,
        mail_store: MailStore | None,
        registry: ToolRegistry,
        clock: Clock,
        offset_minutes: int,
    ) -> None:
        self._alerts = alerts
        self._deadlines = deadlines
        self._autocal = autocal
        self._mail = mail_store
        self._registry = registry
        self._clock = clock
        self._offset = offset_minutes

    def run(self) -> None:
        steps: tuple[tuple[str, Callable[[], object]], ...] = (
            ("autocal", self._autocal.run),
            ("alerts", self._raise_alerts),
            ("prune", self._alerts.prune),
        )
        for name, step in steps:
            try:
                step()
            except Exception as exc:
                log.warning("alert job step %s failed: %s", name, type(exc).__name__)

    def _raise_alerts(self) -> None:
        settings = self._alerts.settings()
        now = self._clock()
        if settings.deadlines:
            self._deadline_alerts(now)
        if settings.briefing:
            self._briefing(now, settings.briefing_time)

    def _deadline_alerts(self, now: datetime) -> None:
        for item in self._deadlines.store.upcoming(2, self._offset, now=now):
            for stage in _deadline_stages(item, now, self._offset):
                self._alerts.add(
                    "deadline",
                    f"deadline:{item.id}:{stage}:{item.due.isoformat()}",
                    f"{_STAGE_TITLES[stage]}: {item.title}",
                    deadline_body(item, self._offset),
                    {"type": "deadline", "deadline_id": item.id},
                )

    def _briefing(self, now: datetime, briefing_time: str) -> None:
        local = now.astimezone(local_tz(self._offset))
        hour, minute = (int(part) for part in briefing_time.split(":"))
        scheduled = datetime.combine(local.date(), time(hour, minute), tzinfo=local.tzinfo)
        key = f"briefing:{local.date().isoformat()}"
        if not scheduled <= local <= scheduled + BRIEFING_GRACE or self._alerts.exists(key):
            return
        self._alerts.add(
            "briefing", key, "Morning briefing", self._briefing_body(now), {"type": "today"}
        )

    def _briefing_body(self, now: datetime) -> str:
        parts: list[str] = []
        first_subject = ""
        if self._mail is not None:
            since_ms = int((now - timedelta(hours=24)).timestamp() * 1000)
            important = self._mail.recent(since_ms, category="important", limit=100)
            if important:
                parts.append(_plural(len(important), "important mail"))
                first_subject = important[0].subject
        due = len(self._deadlines.list_upcoming(BRIEFING_DEADLINE_DAYS))
        if due:
            parts.append(f"{due} due this week")
        events = self._events_today(now)
        if events:
            parts.append(_plural(events, "event") + " today")
        body = " · ".join(parts) or "Nothing urgent today"
        subject = one_line(first_subject, 100)
        return f"{body} · Top: {subject}" if subject else body

    def _events_today(self, now: datetime) -> int:
        tool = self._registry.get("calendar_events")
        if tool is None or tool.kind is not ToolKind.READ:
            return 0
        try:
            events = tool.run({"days": 1, "limit": 50})
            today = now.astimezone(local_tz(self._offset)).date()
            return sum(1 for event in events if _starts_on(event, today, self._offset))
        except Exception as exc:  # the calendar is optional for the briefing
            log.warning("briefing: calendar events unavailable: %s", type(exc).__name__)
            return 0


def _starts_on(event: object, day: date, offset_minutes: int) -> bool:
    start = event.get("start") if isinstance(event, dict) else None
    if not isinstance(start, str):
        return False
    try:
        if "T" not in start:
            return date.fromisoformat(start) == day
        moment = datetime.fromisoformat(start)
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(local_tz(offset_minutes)).date() == day


class ImportantMailAlerts:
    """MailSync hooks: one alert per newly classified important mail, at most five per sync pass,
    with a single summary alert per account for the rest."""

    def __init__(self, alerts: AlertStore, mail_store: MailStore, clock: Clock) -> None:
        self._alerts = alerts
        self._mail = mail_store
        self._clock = clock
        self._sent = 0
        self._overflow: dict[str, tuple[str, int]] = {}  # account -> (first mail id, count)

    def begin_pass(self) -> None:
        self._sent = 0
        self._overflow = {}

    def on_new_mail(self, msg: MailMessage) -> None:
        if SKIPPED_LABELS & set(msg.label_ids) or not self._alerts.settings().important_mail:
            return
        stored = self._mail.get(msg.account, msg.id)
        if stored is None or stored.category != "important":
            return
        received = datetime.fromtimestamp(stored.internal_date / 1000, UTC)
        if self._clock() - received > MAIL_ALERT_MAX_AGE:
            return
        if self._sent >= MAX_MAIL_ALERTS_PER_PASS:
            first, count = self._overflow.get(msg.account, (msg.id, 0))
            self._overflow[msg.account] = (first, count + 1)
            return
        self._sent += 1
        self._alerts.add(
            "important_mail",
            f"mail:{msg.account}/{msg.id}",
            stored.from_name or stored.from_addr,
            stored.subject,
            {"type": "mail", "account": msg.account, "message_id": msg.id},
        )

    def end_pass(self) -> None:
        for account, (first_id, count) in self._overflow.items():
            self._alerts.add(
                "important_mail",
                f"mail-batch:{account}:{first_id}",
                "More important mail",
                _plural(count, "more important mail"),
                {"type": "today"},
            )
        self._overflow = {}
