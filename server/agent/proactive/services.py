"""Wiring for the proactive features, shared by the entry point and tests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from agent.config import Settings
from agent.connectors.classroom import ClassroomApi
from agent.connectors.gcal import OwnCalendarApi
from agent.core.audit import AuditLog
from agent.core.clock import Clock
from agent.core.llm import LLMClient
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.mail.store import MailStore
from agent.proactive.alerts import AlertJob, AlertStore, ImportantMailAlerts
from agent.proactive.autocal import AutoCalendar
from agent.proactive.deadlines import DeadlineCollector, DeadlineStore
from agent.store.crypto import FieldCipher
from agent.store.db import Database

log = logging.getLogger(__name__)


class Fanout[**P]:
    """Calls every added hook with the same arguments; a failing hook never stops the others."""

    def __init__(self) -> None:
        self._hooks: list[Callable[P, object]] = []

    def add(self, hook: Callable[P, object]) -> None:
        self._hooks.append(hook)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> None:
        for hook in self._hooks:
            try:
                hook(*args, **kwargs)
            except Exception as exc:
                log.warning("hook failed: %s", type(exc).__name__)


@dataclass(frozen=True)
class ProactiveServices:
    alerts: AlertStore
    deadlines: DeadlineCollector
    autocal: AutoCalendar
    alert_job: AlertJob
    mail_alerts: ImportantMailAlerts | None
    offset_minutes: int


def setup_proactive(
    settings: Settings,
    db: Database,
    db_key: bytes,
    registry: ToolRegistry,
    clock: Clock,
    *,
    mail_store: MailStore | None,
    classifier_llm: LLMClient | None,
    classroom_api_for: Callable[[str], ClassroomApi] | None,
    own_calendar_api_for: Callable[[str], OwnCalendarApi] | None,
) -> ProactiveServices:
    cipher = FieldCipher(db_key)
    offset = settings.finance_utc_offset_minutes
    store = DeadlineStore(db, cipher, clock)
    alerts = AlertStore(db, cipher, clock, settings.briefing_time)
    collector = DeadlineCollector(
        store,
        db=db,
        mail_store=mail_store,
        redactor=Redactor(settings.redaction_emails),
        llm=classifier_llm,
        classroom_api_for=classroom_api_for,
        classroom_accounts=settings.classroom_accounts,
        clock=clock,
        horizon_days=settings.deadline_horizon_days,
        offset_minutes=offset,
        vip_senders=frozenset(addr.lower() for addr in settings.vip_senders),
        college_domains=frozenset(domain.lower() for domain in settings.college_domains),
        ignored_senders=frozenset(s.lower() for s in settings.deadline_ignore_senders),
    )
    calendar = settings.deadline_calendar
    autocal = AutoCalendar(
        db,
        store,
        own_calendar_api_for or _no_calendar,
        calendar if own_calendar_api_for is not None else None,
        clock,
        AuditLog(db, clock),
        alerts,
        settings.calendar_auto_add,
        offset,
    )
    job = AlertJob(alerts, collector, autocal, mail_store, registry, clock, offset)
    mail_alerts = ImportantMailAlerts(alerts, mail_store, clock) if mail_store else None
    return ProactiveServices(alerts, collector, autocal, job, mail_alerts, offset)


def _no_calendar(account: str) -> OwnCalendarApi:
    raise LookupError("no calendar is configured")
