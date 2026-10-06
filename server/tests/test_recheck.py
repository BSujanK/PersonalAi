"""``agent deadlines-recheck``: finding and removing mail deadlines the new rules reject."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import agent.main as main_module
from agent.core.audit import AuditLog
from agent.mail.store import MailStore
from agent.proactive.deadlines import DeadlineStore
from agent.proactive.recheck import Rejected, apply_rejections, find_rejected
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import InsecureKeyringError, KeyStore
from tests.proactive_support import COLLEGE, ME, FakeOwnCalendarApi, ProEnv, mail_message, make_env
from tests.support import START, FakeClock

NEWSLETTERS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "newsletters.json").read_text(encoding="utf-8")
)
MARKET = NEWSLETTERS[0]
FAR_DATE = "Please submit the form" + " ok" * 25 + " 20 October"  # date 75 characters away
MARKER = "0123456789abcdef0123456789abcdef"


def _newsletter(message_id: str, **changes: Any) -> Any:
    fields: dict[str, Any] = {
        "from_addr": MARKET["from_addr"],
        "from_name": MARKET["from_name"],
        "subject": MARKET["subject"],
        "body": MARKET["body"],
        "label_ids": tuple(MARKET["label_ids"]),
        "list_unsubscribe": MARKET["list_unsubscribe"],
    }
    fields.update(changes)
    return mail_message(message_id, **fields)


def _legacy(
    env: ProEnv,
    message_id: str,
    due: date,
    *,
    kind: str = "event",
    found_by: str = "rule",
    store_mail: Any = None,
) -> int:
    """A mail deadline as an older version would have stored it."""
    if store_mail is not None:
        env.store_mail(store_mail)
    store = env.services.deadlines.store
    assert store.insert(
        source="mail",
        source_key=f"{ME}/{message_id}/{due.isoformat()}",
        source_account=ME,
        source_id=message_id,
        kind=kind,
        title=f"title {message_id}",
        due=due,
        found_by=found_by,
    )
    [row] = env.db.query("SELECT id FROM deadlines WHERE source_id = ?", (message_id,))
    return int(row["id"])


def _world() -> tuple[ProEnv, dict[str, int]]:
    """Deadlines: two newsletter ones (one on the calendar, one not), one whose date is too far
    from its keyword (on the calendar), a legitimate one, a model-found one, one without stored
    mail, and a Classroom one."""
    env = make_env()
    ids = {
        "newsletter_cal": _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1")),
        "far": _legacy(
            env,
            "far",
            date(2026, 10, 20),
            kind="submission",
            store_mail=mail_message("far", body=FAR_DATE),
        ),
        "legit": _legacy(
            env,
            "legit",
            date(2026, 10, 12),
            kind="fee",
            store_mail=mail_message("legit"),
        ),
        "llm": _legacy(
            env,
            "llm",
            date(2026, 10, 20),
            kind="submission",
            found_by="llm",
            store_mail=mail_message("llm", body=FAR_DATE),
        ),
        "no_mail": _legacy(env, "gone", date(2026, 10, 14)),
    }
    assert env.services.deadlines.store.insert(
        source="classroom",
        source_key=f"{COLLEGE}/c1/w1",
        source_account=COLLEGE,
        source_id="w1",
        kind="submission",
        title="Essay (Course)",
        due=date(2026, 10, 15),
        found_by="classroom",
    )
    [row] = env.db.query("SELECT id FROM deadlines WHERE source = 'classroom'")
    ids["classroom"] = int(row["id"])
    assert env.services.autocal.run() == len(ids)  # everything is on the calendar
    ids["newsletter_off"] = _legacy(
        env, "n2", date(2026, 10, 10), store_mail=_newsletter("n2", subject="Another wrap")
    )
    return env, ids


def _find(env: ProEnv) -> list[Rejected]:
    return find_rejected(
        env.db,
        env.services.deadlines.store,
        env.mail,
        env.settings,
        env.settings.finance_utc_offset_minutes,
    )


def _statuses(env: ProEnv) -> dict[int, str]:
    return {r["id"]: r["status"] for r in env.db.query("SELECT id, status FROM deadlines")}


# --- finding -----------------------------------------------------------------------------------


def test_finds_the_rejected_deadlines_and_nothing_else() -> None:
    env, ids = _world()
    found = {r.deadline_id: r for r in _find(env)}
    assert set(found) == {ids["newsletter_cal"], ids["newsletter_off"], ids["far"]}
    assert found[ids["newsletter_cal"]].reason == "bulk_mail:list_unsubscribe"
    assert found[ids["newsletter_cal"]].on_calendar is True
    assert found[ids["newsletter_off"]].on_calendar is False
    assert found[ids["far"]].reason == "rule_no_longer_matches"
    first = found[ids["newsletter_cal"]]
    assert (first.kind, first.due, first.account, first.title) == (
        "event",
        date(2026, 10, 8),
        ME,
        "title n1",
    )


def test_finding_changes_nothing() -> None:
    env, _ = _world()
    before = (_statuses(env), dict(env.calendar.events), env.db.query("SELECT * FROM audit_log"))
    _find(env)
    after = (_statuses(env), dict(env.calendar.events), env.db.query("SELECT * FROM audit_log"))
    assert before == after
    assert env.calendar.deleted == []


def test_a_trusted_sender_is_not_rejected_as_bulk() -> None:
    env = make_env(vip_senders=(MARKET["from_addr"],))
    _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1"))
    assert _find(env) == []


def test_only_active_mail_deadlines_are_looked_at() -> None:
    env = make_env()
    deadline_id = _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1"))
    env.db.execute("UPDATE deadlines SET status = 'undone' WHERE id = ?", (deadline_id,))
    assert _find(env) == []


def test_a_rule_deadline_that_still_matches_is_kept() -> None:
    env = make_env()
    _legacy(env, "m1", date(2026, 10, 12), kind="fee", store_mail=mail_message("m1"))
    assert _find(env) == []


# --- applying ----------------------------------------------------------------------------------


def test_apply_undoes_dismisses_and_leaves_the_rest() -> None:
    env, ids = _world()
    audit = AuditLog(env.db, env.clock)
    counts = apply_rejections(_find(env), env.services.autocal, env.db, audit)
    assert (counts.undone, counts.dismissed, counts.refused, counts.failed) == (2, 1, 0, 0)

    statuses = _statuses(env)
    for name in ("newsletter_cal", "newsletter_off", "far"):
        assert statuses[ids[name]] == "undone", name
    for name in ("legit", "llm", "no_mail", "classroom"):
        assert statuses[ids[name]] == "active", name
    # the events of the two undone deadlines are gone, the others are still there
    assert env.calendar.deleted == ["auto1", "auto2"]
    assert len(env.calendar.events) == 4
    on_calendar = env.services.deadlines.store.calendar_added_ids(list(ids.values()))
    assert on_calendar == {ids[n] for n in ("legit", "llm", "no_mail", "classroom")}

    undo = env.db.query("SELECT actor, detail FROM audit_log WHERE event = 'calendar_auto_undo'")
    assert sorted((r["actor"], r["detail"]) for r in undo) == sorted(
        ("cli:recheck", f"deadline:{ids[n]}") for n in ("newsletter_cal", "far")
    )
    dismissed = env.db.query(
        "SELECT actor, detail FROM audit_log WHERE event = 'deadline_dismissed'"
    )
    assert [(r["actor"], r["detail"]) for r in dismissed] == [
        ("cli:recheck", f"deadline:{ids['newsletter_off']}")
    ]
    assert audit.verify()


def test_a_dismissed_deadline_is_never_added_to_the_calendar() -> None:
    env, _ = _world()
    apply_rejections(_find(env), env.services.autocal, env.db, AuditLog(env.db, env.clock))
    before = len(env.calendar.inserted)
    assert env.services.autocal.run() == 0
    assert len(env.calendar.inserted) == before
    assert _find(env) == []  # a second run finds nothing to do


def test_a_refused_undo_is_counted_and_not_marked() -> None:
    env = make_env()
    deadline_id = _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1"))
    env.services.autocal.run()
    [event] = env.calendar.events.values()
    event["extendedProperties"]["private"]["personalai_auto"] = "someone-elses-marker"

    counts = apply_rejections(_find(env), env.services.autocal, env.db, AuditLog(env.db, env.clock))

    assert (counts.undone, counts.dismissed, counts.refused, counts.failed) == (0, 0, 1, 0)
    assert env.calendar.deleted == [] and len(env.calendar.events) == 1
    assert _statuses(env)[deadline_id] == "active"
    assert env.db.query("SELECT * FROM auto_events WHERE undone_at IS NOT NULL") == []
    assert env.db.query("SELECT * FROM audit_log WHERE actor = 'cli:recheck'") == []


def test_one_failure_does_not_stop_the_others() -> None:
    env = make_env()
    first = _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1"))
    second = _legacy(env, "n2", date(2026, 10, 9), store_mail=_newsletter("n2"))
    env.services.autocal.run()
    real = env.calendar.delete_own
    calls: list[str] = []

    def flaky(event_id: str, marker: str) -> None:
        calls.append(event_id)
        if event_id == "auto1":
            raise ConnectionError("down")
        real(event_id, marker)

    env.calendar.delete_own = flaky  # type: ignore[method-assign]
    counts = apply_rejections(_find(env), env.services.autocal, env.db, AuditLog(env.db, env.clock))
    assert calls == ["auto1", "auto2"]
    assert (counts.undone, counts.failed) == (1, 1)
    assert _statuses(env) == {first: "active", second: "undone"}


def test_an_item_that_is_no_longer_active_counts_as_failed() -> None:
    env = make_env()
    deadline_id = _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1"))
    [item] = _find(env)
    env.db.execute("UPDATE deadlines SET status = 'undone' WHERE id = ?", (deadline_id,))
    counts = apply_rejections([item], env.services.autocal, env.db, AuditLog(env.db, env.clock))
    assert (counts.undone, counts.dismissed, counts.failed) == (0, 0, 1)
    assert env.db.query("SELECT * FROM audit_log") == []


def test_undo_keeps_the_device_actor_for_the_api() -> None:
    env = make_env()
    _legacy(env, "n1", date(2026, 10, 8), store_mail=_newsletter("n1"))
    env.services.autocal.run()
    assert env.services.autocal.undo(1, "device:dev1") == "undone"
    [row] = env.db.query("SELECT actor FROM audit_log WHERE event = 'calendar_auto_undo'")
    assert row["actor"] == "device:dev1"


# --- the command -------------------------------------------------------------------------------


class Cli:
    """A database on disk seeded the way the server would have left it."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path)
        key = KeyStore().get_or_create_bytes("db_key")
        cipher = FieldCipher(key)
        clock = FakeClock()
        self.mail = MailStore(self.db, cipher, key, clock)
        self.deadlines = DeadlineStore(self.db, cipher, clock)

    def add(self, message_id: str, due: date, *, on_calendar: bool, **mail: Any) -> int:
        self.mail.upsert(_newsletter(message_id, **mail))
        self.deadlines.insert(
            source="mail",
            source_key=f"{ME}/{message_id}/{due.isoformat()}",
            source_account=ME,
            source_id=message_id,
            kind="event",
            title="Crude down",
            due=due,
            found_by="rule",
        )
        [row] = self.db.query("SELECT id FROM deadlines WHERE source_id = ?", (message_id,))
        if on_calendar:
            self.db.execute(
                "INSERT INTO auto_events (deadline_id, calendar_account, event_id, marker, "
                "created_at) VALUES (?, ?, 'auto1', ?, ?)",
                (row["id"], ME, MARKER, START.isoformat()),
            )
        return int(row["id"])


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Cli:
    path = tmp_path / "agent.db"
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(path))
    monkeypatch.setenv("PERSONALAI_MAIL_ACCOUNTS", ME)
    monkeypatch.setenv("PERSONALAI_CALENDAR_ACCOUNTS", ME)
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    return Cli(path)


@pytest.fixture
def calendar(monkeypatch: pytest.MonkeyPatch) -> FakeOwnCalendarApi:
    fake = FakeOwnCalendarApi()
    fake.events["auto1"] = {
        "id": "auto1",
        "summary": "Due: Crude down",
        "extendedProperties": {"private": {"personalai_auto": MARKER}},
    }
    monkeypatch.setattr(main_module, "build_own_calendar_api", lambda account, auth: fake)
    return fake


def test_the_command_is_a_dry_run_by_default(
    cli: Cli, calendar: FakeOwnCalendarApi, capsys: pytest.CaptureFixture[str]
) -> None:
    on = cli.add("n1", date(2026, 10, 8), on_calendar=True)
    off = cli.add("n2", date(2026, 10, 9), on_calendar=False)

    assert main_module.main(["deadlines-recheck"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"{on}  event  2026-10-08  {ME}  Crude down  on calendar: yes  bulk_mail:list_unsubscribe",
        f"{off}  event  2026-10-09  {ME}  Crude down  on calendar: no  bulk_mail:list_unsubscribe",
        "dry run: nothing changed; re-run with --apply",
    ]
    assert calendar.deleted == [] and "auto1" in calendar.events
    assert {r["status"] for r in cli.db.query("SELECT status FROM deadlines")} == {"active"}
    assert cli.db.query("SELECT * FROM audit_log") == []


def test_the_command_applies_with_the_flag(
    cli: Cli, calendar: FakeOwnCalendarApi, capsys: pytest.CaptureFixture[str]
) -> None:
    on = cli.add("n1", date(2026, 10, 8), on_calendar=True)
    off = cli.add("n2", date(2026, 10, 9), on_calendar=False)

    assert main_module.main(["deadlines-recheck", "--apply"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "undone 1, dismissed 1, refused 0, failed 0"
    assert "dry run" not in "\n".join(out)
    assert calendar.deleted == ["auto1"]
    statuses = {r["id"]: r["status"] for r in cli.db.query("SELECT id, status FROM deadlines")}
    assert statuses == {on: "undone", off: "undone"}
    events = {r["event"]: r["actor"] for r in cli.db.query("SELECT event, actor FROM audit_log")}
    assert events == {
        "calendar_auto_undo": "cli:recheck",
        "deadline_dismissed": "cli:recheck",
    }


def test_the_command_with_nothing_to_do(
    cli: Cli, calendar: FakeOwnCalendarApi, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main_module.main(["deadlines-recheck", "--apply"]) == 0
    assert capsys.readouterr().out == "No wrongly found mail deadlines.\n"
    assert calendar.deleted == []


def test_the_command_without_mail_accounts(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PERSONALAI_MAIL_ACCOUNTS")
    assert main_module.main(["deadlines-recheck"]) == 0
    assert "No mail accounts are configured" in capsys.readouterr().out


def test_the_command_refuses_an_insecure_keyring(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> None:
    def insecure() -> None:
        raise InsecureKeyringError("no secure keyring")

    monkeypatch.setattr(main_module, "assert_secure_backend", insecure)
    assert main_module.main(["deadlines-recheck"]) == main_module.EXIT_REFUSED
