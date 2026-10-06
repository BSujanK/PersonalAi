from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from agent.connectors.gmail import MailMessage
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.mail.sync import MailSync
from agent.proactive.alerts import AlertSettings
from agent.proactive.services import Fanout
from tests.fakes_gmail import FakeGmailApi
from tests.proactive_support import ME, ProEnv, mail_message, make_env
from tests.support import START

IST = timezone(timedelta(minutes=330))


def _add(
    env: ProEnv, key: str, due: date | datetime, title: str = "Tuition fee", kind: str = "fee"
) -> None:
    env.services.deadlines.store.insert(
        source="mail",
        source_key=key,
        source_account=ME,
        source_id=key,
        kind=kind,
        title=title,
        due=due,
        found_by="rule",
    )


def _alerts(env: ProEnv, kind: str | None = None) -> list[Any]:
    return [a for a in env.services.alerts.since(0, 100) if kind in (None, a.kind)]


def _set_local(env: ProEnv, day: int, hour: int, minute: int = 0, month: int = 10) -> None:
    env.clock.now = datetime(2026, month, day, hour, minute, tzinfo=IST)


# --- the store ---------------------------------------------------------------------------------


def test_add_is_deduplicated_and_sanitised() -> None:
    env = make_env()
    alerts = env.services.alerts
    target = {"type": "today"}
    assert alerts.add("briefing", "k1", "T\nitle " + "x" * 200, "B​o\tdy " + "y" * 400, target)
    assert not alerts.add("briefing", "k1", "other", "other", target)
    [alert] = alerts.since(0, 10)
    assert len(alert.title) == 80 and "\n" not in alert.title
    assert alert.title.startswith("T itle ")
    assert len(alert.body) == 300 and alert.body.startswith("Bo dy ")
    assert (alert.kind, alert.target, alert.actions) == ("briefing", target, ())
    assert alert.created_at == START.isoformat()


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        make_env().services.alerts.add("push", "k", "t", "b", {"type": "today"})


def test_content_is_encrypted_at_rest() -> None:
    env = make_env()
    env.services.alerts.add("briefing", "k1", "Secret title", "Secret body", {"type": "today"})
    [row] = env.db.query("SELECT * FROM alerts")
    assert b"Secret" not in row["content_enc"]


def test_since_is_ascending_after_and_limited() -> None:
    env = make_env()
    for i in range(5):
        env.services.alerts.add("briefing", f"k{i}", f"T{i}", "b", {"type": "today"})
    assert [a.id for a in env.services.alerts.since(0, 100)] == [1, 2, 3, 4, 5]
    assert [a.id for a in env.services.alerts.since(2, 100)] == [3, 4, 5]
    assert [a.id for a in env.services.alerts.since(0, 2)] == [1, 2]
    assert env.services.alerts.since(5, 10) == []


def test_latest_id_never_goes_backwards_after_pruning() -> None:
    env = make_env()
    alerts = env.services.alerts
    assert alerts.latest_id() == 0
    alerts.add("briefing", "k1", "t", "b", {"type": "today"})
    alerts.add("briefing", "k2", "t", "b", {"type": "today"})
    assert alerts.latest_id() == 2
    env.clock.advance(timedelta(days=15))
    assert alerts.prune() == 2
    assert alerts.latest_id() == 2
    alerts.add("briefing", "k3", "t", "b", {"type": "today"})
    assert [a.id for a in alerts.since(2, 10)] == [3]


def test_prune_keeps_the_last_14_days() -> None:
    env = make_env()
    alerts = env.services.alerts
    alerts.add("briefing", "old", "t", "b", {"type": "today"})
    env.clock.advance(timedelta(days=13, hours=23))
    alerts.add("briefing", "new", "t", "b", {"type": "today"})
    env.clock.advance(timedelta(hours=2))  # "old" is now 14 days and 1 hour old
    assert alerts.prune() == 1
    assert [a.id for a in alerts.since(0, 10)] == [2]


def test_settings_default_to_on_with_the_configured_time_and_can_be_saved() -> None:
    env = make_env(briefing_time="06:45")
    alerts = env.services.alerts
    assert alerts.settings() == AlertSettings(True, True, True, "06:45")
    saved = alerts.save_settings(AlertSettings(False, True, False, "21:05"))
    assert saved == AlertSettings(False, True, False, "21:05")
    assert alerts.settings() == saved
    assert len(env.db.query("SELECT * FROM alert_settings")) == 1


# --- deadline alerts ---------------------------------------------------------------------------


def test_timed_deadline_alerts_one_day_and_two_hours_before() -> None:
    env = make_env()
    due = datetime(2026, 10, 6, 23, 30, tzinfo=IST)  # 18:00 UTC; 30h after START
    _add(env, "a", due)
    job = env.services.alert_job
    job.run()
    assert _alerts(env, "deadline") == []  # more than 24h away
    env.clock.now = due - timedelta(hours=24)
    job.run()
    job.run()
    [first] = _alerts(env, "deadline")
    assert first.title == "Due tomorrow: Tuition fee"
    assert first.body == "Fee · Tue 06 Oct 23:30"
    assert first.target == {"type": "deadline", "deadline_id": 1} and first.actions == ()
    env.clock.now = due - timedelta(hours=2, minutes=1)
    job.run()
    assert len(_alerts(env, "deadline")) == 1  # still the same one-day alert
    env.clock.now = due - timedelta(hours=2)
    job.run()
    job.run()
    titles = [a.title for a in _alerts(env, "deadline")]
    assert titles == ["Due tomorrow: Tuition fee", "Due in 2 hours: Tuition fee"]
    env.clock.now = due
    job.run()
    assert len(_alerts(env, "deadline")) == 2  # nothing once it is due


def test_all_day_deadline_alerts_from_nine_the_day_before_and_never_two_hours() -> None:
    env = make_env()
    _add(env, "a", date(2026, 10, 7))
    job = env.services.alert_job
    _set_local(env, 6, 8, 59)
    job.run()
    assert _alerts(env, "deadline") == []
    _set_local(env, 6, 9, 0)
    job.run()
    [alert] = _alerts(env, "deadline")
    assert alert.title == "Due tomorrow: Tuition fee" and alert.body == "Fee · Wed 07 Oct"
    _set_local(env, 6, 23, 59)
    job.run()
    _set_local(env, 7, 0, 0)  # the day itself: the one-day window is over
    job.run()
    _set_local(env, 7, 12, 0)
    job.run()
    assert len(_alerts(env, "deadline")) == 1


def test_a_moved_due_date_alerts_again() -> None:
    env = make_env()
    _add(env, "a", date(2026, 10, 7))
    _set_local(env, 6, 10)
    env.services.alert_job.run()
    env.db.execute("UPDATE deadlines SET due = '2026-10-08'")
    _set_local(env, 7, 10)
    env.services.alert_job.run()
    assert len(_alerts(env, "deadline")) == 2


def test_deadline_alerts_follow_the_setting_and_skip_undone_deadlines() -> None:
    env = make_env()
    _add(env, "a", date(2026, 10, 7))
    _add(env, "b", date(2026, 10, 7))
    env.db.execute("UPDATE deadlines SET status = 'undone' WHERE id = 2")
    _set_local(env, 6, 10)
    env.services.alerts.save_settings(AlertSettings(True, False, True, "07:30"))
    env.services.alert_job.run()
    assert _alerts(env, "deadline") == []
    env.services.alerts.save_settings(AlertSettings(True, True, True, "07:30"))
    env.services.alert_job.run()
    [alert] = _alerts(env, "deadline")
    assert alert.target == {"type": "deadline", "deadline_id": 1}


def test_long_titles_are_cut_to_the_alert_limit() -> None:
    env = make_env()
    _add(env, "a", date(2026, 10, 7), title="x" * 150)
    _set_local(env, 6, 10)
    env.services.alert_job.run()
    [alert] = _alerts(env, "deadline")
    assert len(alert.title) == 80 and alert.title.startswith("Due tomorrow: xxx")


def test_the_job_adds_to_the_calendar_before_raising_alerts() -> None:
    env = make_env()
    _add(env, "a", date(2026, 10, 7))
    _set_local(env, 6, 11)
    env.services.alert_job.run()
    assert [a.kind for a in _alerts(env)] == ["calendar_added", "deadline"]


def test_a_failing_step_does_not_stop_the_others(caplog: pytest.LogCaptureFixture) -> None:
    env = make_env()
    _add(env, "a", date(2026, 10, 7))
    _set_local(env, 6, 11)

    def boom() -> int:
        raise RuntimeError("calendar secret detail")

    env.services.autocal.run = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO, logger="agent"):
        env.services.alert_job.run()
    assert [a.kind for a in _alerts(env)] == ["deadline"]
    assert "RuntimeError" in caplog.text and "secret" not in caplog.text


# --- the morning briefing ----------------------------------------------------------------------


def _calendar_tool(events: list[dict[str, Any]] | Exception) -> ToolRegistry:
    registry = ToolRegistry()

    def run(args: dict[str, Any]) -> Any:
        if isinstance(events, Exception):
            raise events
        return events

    registry.register(
        Tool(
            name="calendar_events",
            description="events",
            parameters={"type": "object", "properties": {}},
            kind=ToolKind.READ,
            run=run,
        )
    )
    return registry


def _important(env: ProEnv, message_id: str, subject: str, hours_ago: float) -> None:
    ms = int((env.clock.now - timedelta(hours=hours_ago)).timestamp() * 1000)
    env.store_mail(mail_message(message_id, subject=subject, internal_date=ms), "important")


def test_briefing_is_built_locally_once_per_day_in_its_window() -> None:
    env = make_env(
        registry=_calendar_tool(
            [
                {"start": "2026-10-06T10:00:00+05:30"},
                {"start": "2026-10-06"},
                {"start": "2026-10-07T09:00:00+05:30"},  # tomorrow
                {"start": 5},
                "nonsense",
            ]
        )
    )
    _set_local(env, 6, 7, 40)
    _important(env, "a", "Older mail", hours_ago=10)
    _important(env, "b", "Scholarship interview", hours_ago=1)
    _important(env, "c", "Too old", hours_ago=30)
    env.store_mail(mail_message("n", subject="Newsletter"), "normal")
    _add(env, "d1", date(2026, 10, 9))
    _add(env, "d2", date(2026, 10, 20))  # not this week
    env.services.alert_job.run()
    env.services.alert_job.run()
    [briefing] = _alerts(env, "briefing")
    assert briefing.title == "Morning briefing"
    assert briefing.body == (
        "2 important mails · 1 due this week · 2 events today · Top: Scholarship interview"
    )
    assert briefing.target == {"type": "today"}
    _set_local(env, 7, 7, 40)
    env.services.alert_job.run()
    assert len(_alerts(env, "briefing")) == 2


def test_briefing_window_starts_at_the_time_and_ends_after_three_hours() -> None:
    env = make_env()
    job = env.services.alert_job
    _set_local(env, 6, 7, 29)
    job.run()
    assert _alerts(env, "briefing") == []
    _set_local(env, 6, 10, 31)  # more than three hours late: no stale briefing
    job.run()
    assert _alerts(env, "briefing") == []
    _set_local(env, 6, 10, 30)
    job.run()
    assert len(_alerts(env, "briefing")) == 1


def test_briefing_uses_the_time_saved_from_the_phone() -> None:
    env = make_env()
    env.services.alerts.save_settings(AlertSettings(True, True, True, "21:00"))
    _set_local(env, 6, 7, 40)
    env.services.alert_job.run()
    assert _alerts(env, "briefing") == []
    _set_local(env, 6, 21, 5)
    env.services.alert_job.run()
    [briefing] = _alerts(env, "briefing")
    assert briefing.body == "Nothing urgent today"


def test_briefing_off_and_singular_wording() -> None:
    env = make_env()
    _set_local(env, 6, 7, 40)
    _important(env, "a", "Only one", hours_ago=1)
    env.services.alerts.save_settings(AlertSettings(True, True, False, "07:30"))
    env.services.alert_job.run()
    assert _alerts(env, "briefing") == []
    env.services.alerts.save_settings(AlertSettings(True, True, True, "07:30"))
    env.services.alert_job.run()
    assert _alerts(env, "briefing")[0].body == "1 important mail · Top: Only one"


def test_briefing_ignores_a_failing_calendar_and_carries_no_money_content() -> None:
    env = make_env(registry=_calendar_tool(RuntimeError("calendar offline")))
    _set_local(env, 6, 7, 40)
    _add(env, "d1", date(2026, 10, 9))
    env.services.alert_job.run()
    [briefing] = _alerts(env, "briefing")
    assert briefing.body == "1 due this week"
    for word in ("balance", "spent", "₹", "Rs", "INR", "debit"):
        assert word not in briefing.body


# --- important mail alerts ---------------------------------------------------------------------


def test_important_mail_alert_has_sender_subject_and_target() -> None:
    env = make_env()
    msg = mail_message("a", subject="Interview call", from_name="Dean Rao")
    env.store_mail(msg, "important")
    env.services.mail_alerts.on_new_mail(msg)  # type: ignore[union-attr]
    [alert] = _alerts(env, "important_mail")
    assert (alert.title, alert.body) == ("Dean Rao", "Interview call")
    assert alert.target == {"type": "mail", "account": ME, "message_id": "a"}
    env.services.mail_alerts.on_new_mail(msg)  # type: ignore[union-attr]
    assert len(_alerts(env, "important_mail")) == 1


def test_only_recent_important_mail_with_the_setting_on_alerts() -> None:
    env = make_env()
    hook = env.services.mail_alerts
    assert hook is not None
    old_ms = int((env.clock.now - timedelta(hours=6, minutes=1)).timestamp() * 1000)
    cases = [
        (mail_message("old", internal_date=old_ms), "important"),
        (mail_message("normal"), "normal"),
        (mail_message("promo"), "promo"),
        (mail_message("none"), None),
        (mail_message("sent", label_ids=("SENT",)), "important"),
        (mail_message("spam", label_ids=("SPAM",)), "important"),
    ]
    for msg, category in cases:
        env.store_mail(msg, category)
        hook.on_new_mail(msg)
    hook.on_new_mail(mail_message("unstored"))
    assert _alerts(env) == []
    env.services.alerts.save_settings(AlertSettings(False, True, True, "07:30"))
    fresh = env.store_mail(mail_message("fresh"), "important")
    hook.on_new_mail(fresh)
    assert _alerts(env) == []


def test_at_most_five_alerts_per_pass_and_one_summary_per_account() -> None:
    env = make_env()
    hook = env.services.mail_alerts
    assert hook is not None
    hook.begin_pass()
    for i in range(9):
        msg = env.store_mail(mail_message(f"m{i}"), "important")
        hook.on_new_mail(msg)
    other = env.store_mail(mail_message("x0", account="two@example.org"), "important")
    hook.on_new_mail(other)
    hook.end_pass()
    alerts = _alerts(env, "important_mail")
    assert [a.title for a in alerts[:5]] == ["Registrar"] * 5
    summary = alerts[5:]
    assert [(a.title, a.body, a.target) for a in summary] == [
        ("More important mail", "4 more important mails", {"type": "today"}),
        ("More important mail", "1 more important mail", {"type": "today"}),
    ]
    hook.end_pass()  # nothing is repeated
    assert len(_alerts(env, "important_mail")) == 7
    hook.begin_pass()
    msg = env.store_mail(mail_message("next"), "important")
    hook.on_new_mail(msg)
    assert len(_alerts(env, "important_mail")) == 8


def test_overflow_summary_is_deduplicated_by_its_first_mail() -> None:
    env = make_env()
    hook = env.services.mail_alerts
    assert hook is not None
    for _ in range(2):
        hook.begin_pass()
        for i in range(6):
            hook.on_new_mail(env.store_mail(mail_message(f"m{i}"), "important"))
        hook.end_pass()
    assert len(_alerts(env, "important_mail")) == 6  # five, plus one summary (same first id)


# --- through MailSync --------------------------------------------------------------------------


class _StubClassifier:
    def __init__(self, env: ProEnv, category: str) -> None:
        self._env, self._category = env, category

    def classify(self, msg: MailMessage) -> object:
        self._env.mail.set_category(msg.account, msg.id, self._category, "rule", "stub")
        return None


def test_mail_sync_drives_the_hooks_in_order_and_isolates_failures() -> None:
    env = make_env()
    api = FakeGmailApi(ME, page_size=100)
    now_ms = int(env.clock.now.timestamp() * 1000)
    for i in range(7):
        api.add_message(f"m{i}", subject=f"Item {i}", internal_date=now_ms - 60_000, body="x")
    api.add_message("fee", subject="Fee", body="Tuition fee due 2026-10-12", internal_date=now_ms)
    mail_alerts = env.services.mail_alerts
    assert mail_alerts is not None

    on_new: Fanout[[MailMessage]] = Fanout()
    pass_start: Fanout[[]] = Fanout()
    pass_end: Fanout[[]] = Fanout()

    def broken(_msg: MailMessage) -> None:
        raise RuntimeError("hook exploded")

    on_new.add(broken)
    on_new.add(env.services.deadlines.on_new_mail)
    on_new.add(mail_alerts.on_new_mail)
    pass_start.add(mail_alerts.begin_pass)
    pass_end.add(mail_alerts.end_pass)
    sync = MailSync(
        env.mail,
        lambda _a: api,
        _StubClassifier(env, "important"),
        env.clock,
        7,
        on_new=on_new,
        on_pass_start=pass_start,
        on_pass_end=pass_end,
    )
    assert not isinstance(sync.sync_all([ME])[ME], str)
    assert len(env.deadlines()) == 1
    alerts = _alerts(env, "important_mail")
    assert len(alerts) == 6  # five individual alerts, one summary for the other three
    assert alerts[-1].body == "3 more important mails"


def test_pass_end_runs_even_when_an_account_fails() -> None:
    env = make_env()
    seen: list[str] = []
    api = FakeGmailApi(ME)

    def api_for(_account: str) -> FakeGmailApi:
        raise PermissionError("no token")

    sync = MailSync(
        env.mail,
        api_for,
        None,
        env.clock,
        7,
        on_pass_start=lambda: seen.append("start"),
        on_pass_end=lambda: seen.append("end"),
    )
    assert sync.sync_all([ME]) == {ME: "PermissionError"}
    assert seen == ["start", "end"]
    assert api.messages == {}
