"""Settings and entry-point wiring of the proactive features."""

from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

import pytest

import agent.main as main_module
from agent.config import Settings
from agent.connectors.google_auth import GoogleAuth
from agent.core.clock import utcnow
from agent.core.tools import ToolRegistry
from agent.mail.services import MailServices
from agent.mail.store import MailStore
from agent.mail.sync import MailSync
from agent.proactive.services import Fanout
from agent.scheduler import ALERT_JOB_ID, CLASSROOM_DEADLINE_JOB_ID
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.workspace.services import WorkspaceServices
from tests.fakes_gmail import FakeGmailApi
from tests.proactive_support import ME, mail_message
from tests.support import FakeClock
from tests.test_main import _capture_jobs, _serve_env

KEY = bytes(range(32))


def test_defaults() -> None:
    settings = Settings.from_env({})
    assert settings.calendar_auto_add is True
    assert settings.alert_poll_minutes == 5
    assert settings.briefing_time == "07:30"


@pytest.mark.parametrize("value", ["0", "false", "off", "no", "FALSE", " Off "])
def test_auto_add_can_be_switched_off(value: str) -> None:
    assert Settings.from_env({"PERSONALAI_CALENDAR_AUTO_ADD": value}).calendar_auto_add is False


@pytest.mark.parametrize("value", ["1", "true", "on", "yes", ""])
def test_auto_add_stays_on_otherwise(value: str) -> None:
    assert Settings.from_env({"PERSONALAI_CALENDAR_AUTO_ADD": value}).calendar_auto_add is True


@pytest.mark.parametrize("value", ["0", "-1", "abc", ""])
def test_alert_poll_minutes_must_be_positive(value: str) -> None:
    with pytest.raises(ValueError, match="PERSONALAI_ALERT_POLL_MINUTES"):
        Settings.from_env({"PERSONALAI_ALERT_POLL_MINUTES": value})
    assert Settings.from_env({"PERSONALAI_ALERT_POLL_MINUTES": "2"}).alert_poll_minutes == 2


@pytest.mark.parametrize("value", ["7:30", "24:00", "07:60", "", "0730", "07:30:00", "ab:cd"])
def test_briefing_time_must_be_hh_mm(value: str) -> None:
    with pytest.raises(ValueError, match="PERSONALAI_BRIEFING_TIME"):
        Settings.from_env({"PERSONALAI_BRIEFING_TIME": value})


@pytest.mark.parametrize("value", ["00:00", "07:30", "23:59"])
def test_briefing_time_accepts_valid_times(value: str) -> None:
    assert Settings.from_env({"PERSONALAI_BRIEFING_TIME": value}).briefing_time == value


def test_serve_refuses_a_bad_news_feed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_NEWS_FEEDS", "http://news.example.com/feed")
    _capture_jobs(monkeypatch)
    assert main_module.main(["serve"]) == main_module.EXIT_REFUSED


def test_alert_job_uses_the_configured_interval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_ALERT_POLL_MINUTES", "10")
    monkeypatch.setenv("PERSONALAI_CALENDAR_ACCOUNTS", "me@example.com")
    monkeypatch.setenv("PERSONALAI_CLASSROOM_ACCOUNTS", "student@example.edu")
    captured, _ = _capture_jobs(monkeypatch)
    assert main_module.main(["serve"]) == 0
    jobs = {job.id: job.minutes for job in captured[0]}
    assert jobs[ALERT_JOB_ID] == 10 and jobs[CLASSROOM_DEADLINE_JOB_ID] == 60


def test_setup_proactive_hooks_mail_sync_into_deadlines_and_alerts() -> None:
    db = Database(":memory:")
    clock = FakeClock()
    store = MailStore(db, FieldCipher(KEY), KEY, clock)
    api = FakeGmailApi(ME)
    sync = MailSync(store, lambda _a: api, None, clock, 7)
    hooks = main_module._MailHooks(Fanout(), Fanout(), Fanout())
    proactive = main_module._setup_proactive(
        Settings(owner_emails=(ME,), mail_accounts=(ME,)),
        db,
        KEY,
        GoogleAuth(KeyStore()),
        ToolRegistry(),
        MailServices(store, sync, lambda _a: api),
        WorkspaceServices(None, None),
        hooks,
    )
    now = utcnow()  # _setup_proactive runs on the real clock
    msg = mail_message(
        "a",
        subject="Tuition fee",
        body="The fee is due tomorrow.",
        internal_date=int(now.timestamp() * 1000),
    )
    store.upsert(msg)
    store.set_category(ME, "a", "important", "rule", "test")
    hooks.pass_start()
    hooks.on_new(msg)
    hooks.pass_end()
    tomorrow = now.astimezone(timezone(timedelta(minutes=330))).date() + timedelta(days=1)
    [deadline] = proactive.deadlines.list_upcoming(30)
    assert (deadline.kind, deadline.due, deadline.title) == ("fee", tomorrow, "Tuition fee")
    [alert] = proactive.alerts.since(0, 10)
    assert alert.kind == "important_mail" and alert.body == "Tuition fee"
