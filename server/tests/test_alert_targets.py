"""Every alert carries a navigable target (ids and the source account only) and, in the feed,
the account it came from and that account's label."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from tests.proactive_support import COLLEGE, ME, ProEnv, mail_message
from tests.test_notifications_api import NotifyApi, _api, _get

IST = timezone(timedelta(minutes=330))
ALLOWED_TARGET_KEYS = {
    "type", "id", "message_id", "account", "source", "deadline_id", "course_id",
}  # fmt: skip


def _insert(env: ProEnv, source: str, key: str, account: str, source_id: str) -> None:
    env.services.deadlines.store.insert(
        source=source,
        source_key=key,
        source_account=account,
        source_id=source_id,
        kind="submission" if source == "classroom" else "fee",
        title="Report: SECRET TITLE",
        due=date(2026, 10, 7),
        found_by="rule",
    )


def _items(api: NotifyApi) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = _get(api, "/notifications")["items"]
    return items


def _assert_only_ids(target: dict[str, Any]) -> None:
    assert set(target) <= ALLOWED_TARGET_KEYS
    for value in target.values():
        assert isinstance(value, str | int | dict)
        if isinstance(value, dict):
            assert set(value) == {"account"}
    assert "SECRET" not in repr(target) and "Subject" not in repr(target)


# --- targets as raised -------------------------------------------------------------------------


def test_classroom_deadline_alert_target_has_account_and_course() -> None:
    api = _api(classroom_accounts=(COLLEGE,))
    _insert(api.env, "classroom", f"{COLLEGE}/c9/w3", COLLEGE, "w3")
    api.env.clock.now = datetime(2026, 10, 6, 10, tzinfo=IST)
    api.env.services.alert_job.run()
    [alert] = [a for a in api.env.services.alerts.since(0, 50) if a.kind == "deadline"]
    assert alert.target == {
        "type": "deadline",
        "deadline_id": 1,
        "source": "classroom",
        "account": COLLEGE,
        "course_id": "c9",
    }


def test_mail_deadline_calendar_added_and_every_kind_hold_only_ids() -> None:
    api = _api()
    api.env.services.alerts.add("briefing", "b", "Morning briefing", "x", {"type": "today"})
    api.env.deliver(mail_message("a", subject="SECRET Tuition fee"), "important")
    msg = mail_message("b")
    api.env.store_mail(msg, "important")
    api.env.services.mail_alerts.on_new_mail(msg)  # type: ignore[union-attr]
    api.env.clock.advance(timedelta(days=1))
    api.env.services.alert_job.run()
    items = _items(api)
    assert {i["kind"] for i in items} >= {"briefing", "important_mail", "calendar_added"}
    for item in items:
        _assert_only_ids(item["target"])
    added = next(i for i in items if i["kind"] == "calendar_added")
    assert added["actions"] == ["undo"]
    assert added["target"]["type"] == "deadline"
    assert added["target"]["source"] == "mail" and added["target"]["account"] == ME


# --- read-time enrichment ----------------------------------------------------------------------


def test_old_format_deadline_alert_is_enriched_from_the_deadline() -> None:
    api = _api()
    _insert(api.env, "mail", "k", ME, "mail-77")
    _insert(api.env, "classroom", f"{COLLEGE}/c1/w2", COLLEGE, "w2")
    alerts = api.env.services.alerts
    alerts.add("deadline", "old1", "Due tomorrow: x", "Fee", {"type": "deadline", "deadline_id": 1})
    alerts.add("deadline", "old2", "Due tomorrow: y", "Sub", {"type": "deadline", "deadline_id": 2})
    alerts.add(
        "deadline", "gone", "Due tomorrow: z", "Gone", {"type": "deadline", "deadline_id": 9}
    )
    first, second, gone = _items(api)
    assert first["target"] == {
        "type": "deadline",
        "deadline_id": 1,
        "source": "mail",
        "account": ME,
        "message_id": "mail-77",
    }
    assert second["target"] == {
        "type": "deadline",
        "deadline_id": 2,
        "source": "classroom",
        "account": COLLEGE,
        "course_id": "c1",
    }
    assert gone["target"] == {"type": "deadline", "deadline_id": 9}
    assert "source_account" not in gone and "source_label" not in gone
    stored = {a.id: a.target for a in alerts.since(0, 10)}
    assert stored[1] == {"type": "deadline", "deadline_id": 1}  # the stored alert is unchanged


def test_old_format_mail_alert_gets_an_id() -> None:
    api = _api()
    api.env.services.alerts.add(
        "important_mail",
        "old",
        "Registrar",
        "Hello",
        {"type": "mail", "account": ME, "message_id": "m5"},
    )
    [item] = _items(api)
    assert item["target"] == {"type": "mail", "account": ME, "message_id": "m5", "id": "m5"}
    assert (item["source_account"], item["source_label"]) == (ME, "Example")


def test_a_target_that_already_has_an_id_is_left_alone() -> None:
    api = _api()
    api.env.services.alerts.add(
        "important_mail",
        "new",
        "Registrar",
        "Hello",
        {"type": "mail", "account": ME, "id": "a", "message_id": "b"},
    )
    [item] = _items(api)
    assert item["target"]["id"] == "a"


# --- source_account / source_label -------------------------------------------------------------


def test_source_account_and_label_present_when_known_and_absent_otherwise() -> None:
    api = _api()
    labelled = replace(api.env.settings, account_labels={COLLEGE: "College"})
    api.client.app.state.settings = labelled  # type: ignore[attr-defined]
    alerts = api.env.services.alerts
    alerts.add("briefing", "b", "Morning briefing", "x", {"type": "today"})
    alerts.add(
        "important_mail", "i", "More important mail", "3", {"type": "inbox", "account": COLLEGE}
    )
    alerts.add(
        "important_mail",
        "m",
        "Dean",
        "Hello",
        {"type": "mail", "id": "a", "source": {"account": ME}},
    )
    briefing, inbox, mail = _items(api)
    assert "source_account" not in briefing and "source_label" not in briefing
    assert (inbox["source_account"], inbox["source_label"]) == (COLLEGE, "College")
    assert (mail["source_account"], mail["source_label"]) == (ME, "Example")
    for item in (briefing, inbox, mail):
        assert set(item) <= {
            "id", "kind", "title", "body", "created_at", "target", "actions",
            "source_account", "source_label",
        }  # fmt: skip


def test_stored_title_and_body_keep_their_format() -> None:
    api = _api()
    msg = mail_message("a", subject="Interview call", from_name="Dean Rao")
    api.env.store_mail(msg, "important")
    api.env.services.mail_alerts.on_new_mail(msg)  # type: ignore[union-attr]
    [alert] = api.env.services.alerts.since(0, 10)
    assert (alert.title, alert.body) == ("Dean Rao", "Interview call")
