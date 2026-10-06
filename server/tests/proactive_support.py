"""Environment for the proactive-agent tests: deadlines, auto-calendar and alerts over fakes.

Synthetic data only (example.com addresses, made-up names)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from agent.config import Settings
from agent.connectors.gcal import EventNotFound, NotOwnEvent
from agent.connectors.gmail import MailMessage
from agent.core.llm import LLMClient
from agent.core.tools import ToolRegistry
from agent.mail.store import MailStore
from agent.proactive.services import ProactiveServices, setup_proactive
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from tests.fakes_workspace import FakeClassroomApi
from tests.support import START, FakeClock

ME = "me@example.com"
COLLEGE = "college@example.org"
KEY = bytes(range(32))


class FakeOwnCalendarApi:
    """Records every call of ``OwnCalendarApi`` and keeps the events it created."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.inserted: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.found: list[str] = []
        self.fail_insert: Exception | None = None
        self.fail_first: int = 0  # fail this many insert calls with a RuntimeError, then work
        self.lose_insert_result: bool = False  # the event is created, then the call "crashes"
        self._next = 1

    def insert_own_event(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.fail_insert is not None:
            raise self.fail_insert
        if self.fail_first > 0:
            self.fail_first -= 1
            raise RuntimeError(f"insert failed for {body['summary']}")
        self.inserted.append(copy.deepcopy(body))
        event = {**copy.deepcopy(body), "id": f"auto{self._next}"}
        self._next += 1
        self.events[event["id"]] = event
        if self.lose_insert_result:
            raise ConnectionError("lost the response")
        return copy.deepcopy(event)

    def find_own(self, marker: str) -> list[dict[str, Any]]:
        self.found.append(marker)
        return [
            copy.deepcopy(e)
            for e in self.events.values()
            if e.get("extendedProperties", {}).get("private", {}).get("personalai_auto") == marker
        ]

    def delete_own(self, event_id: str, marker: str) -> None:
        if event_id not in self.events:
            raise EventNotFound(event_id)
        private = self.events[event_id].get("extendedProperties", {}).get("private", {})
        if private.get("personalai_auto") != marker:
            raise NotOwnEvent(event_id)
        self.deleted.append(event_id)
        del self.events[event_id]


def mail_message(message_id: str = "m1", **changes: Any) -> MailMessage:
    base: dict[str, Any] = {
        "account": ME,
        "id": message_id,
        "thread_id": f"t-{message_id}",
        "history_id": "1",
        "internal_date": int((START - timedelta(hours=1)).timestamp() * 1000),
        "from_addr": "registrar@example.org",
        "from_name": "Registrar",
        "to": (ME,),
        "subject": "Fee reminder",
        "snippet": "snippet",
        "body": "The tuition fee is due on 12 Oct 2026.",
        "label_ids": ("INBOX", "UNREAD"),
        "list_unsubscribe": False,
    }
    base.update(changes)
    return MailMessage(**base)


@dataclass
class ProEnv:
    settings: Settings
    clock: FakeClock
    db: Database
    mail: MailStore
    registry: ToolRegistry
    classroom: FakeClassroomApi
    calendar: FakeOwnCalendarApi
    services: ProactiveServices
    llm: LLMClient | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def store_mail(self, msg: MailMessage, category: str | None = "normal") -> MailMessage:
        """Store a message the way sync does (classified before the new-mail hooks run)."""
        self.mail.upsert(msg)
        if category is not None:
            self.mail.set_category(msg.account, msg.id, category, "rule", "test")
        return msg

    def deliver(self, msg: MailMessage, category: str | None = "normal") -> None:
        self.store_mail(msg, category)
        self.services.deadlines.on_new_mail(msg)

    def deadlines(self, statuses: tuple[str, ...] = ("active", "undone")) -> list[Any]:
        return self.services.deadlines.store.upcoming(
            400, self.settings.finance_utc_offset_minutes, statuses=statuses
        )

    def at(self, **delta: float) -> datetime:
        return START + timedelta(**delta)


def make_env(
    *, llm: LLMClient | None = None, registry: ToolRegistry | None = None, **settings: Any
) -> ProEnv:
    clock = FakeClock()
    db = Database(":memory:")
    mail = MailStore(db, FieldCipher(KEY), KEY, clock)
    chosen = replace(
        Settings(
            owner_emails=(ME,),
            mail_accounts=(ME,),
            calendar_accounts=(ME,),
            classroom_accounts=(COLLEGE,),
        ),
        **settings,
    )
    classroom = FakeClassroomApi()
    calendar = FakeOwnCalendarApi()
    tools = registry if registry is not None else ToolRegistry()
    services = setup_proactive(
        chosen,
        db,
        KEY,
        tools,
        clock,
        mail_store=mail,
        classifier_llm=llm,
        classroom_api_for=lambda _account: classroom,
        own_calendar_api_for=lambda _account: calendar,
    )
    return ProEnv(chosen, clock, db, mail, tools, classroom, calendar, services, llm)
