"""The catch-up scan of stored mail for deadlines: same extraction as new mail, scanned once."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest

from agent.core.llm import ChatMessage, LLMResponse, LLMUnavailable
from agent.core.redact import from_model
from agent.proactive.deadlines import MAIL_SCAN_DAYS, MAIL_SCAN_LIMIT, MAIL_SCAN_MAX_FAILURES
from tests.proactive_support import ME, ProEnv, mail_message, make_env
from tests.test_deadlines import FakeModel

FRIDAY_REPLY = '{"deadlines": [{"kind": "submission", "date": "2026-10-09", "time": null}]}'
NEEDS_MODEL = "Please submit the assignment by Friday."  # a trigger word, but no date


def _ms(env: ProEnv, **ago: float) -> int:
    return int((env.clock.now - timedelta(**ago)).timestamp() * 1000)


def _stored(env: ProEnv, message_id: str, days_ago: float, **changes: Any) -> None:
    changes.setdefault("body", "The tuition fee is due on 2026-10-12.")
    env.store_mail(mail_message(message_id, internal_date=_ms(env, days=days_ago), **changes))


def _scanned_ids(env: ProEnv) -> set[str]:
    return {r["message_id"] for r in env.db.query("SELECT message_id FROM mail_deadline_scans")}


def test_scans_only_unscanned_messages_within_the_window() -> None:
    env = make_env()
    _stored(env, "recent", 5)
    _stored(env, "older-than-the-horizon", 20)  # on_new_mail would have skipped it
    _stored(env, "too-old", MAIL_SCAN_DAYS + 1)
    env.deliver(mail_message("handled", body="Fee due 2026-10-13", internal_date=_ms(env, hours=1)))
    assert _scanned_ids(env) == {"handled"}

    result = env.services.deadlines.scan_stored_mail()

    assert (result.scanned, result.failed, result.added) == (2, 0, 2)
    assert _scanned_ids(env) == {"handled", "recent", "older-than-the-horizon"}
    keys = sorted(r["source_id"] for r in env.db.query("SELECT source_id FROM deadlines"))
    assert keys == ["handled", "older-than-the-horizon", "recent"]


def test_second_run_finds_nothing_new() -> None:
    env = make_env()
    _stored(env, "a", 3)
    _stored(env, "b", 4)
    first = env.services.deadlines.scan_stored_mail()
    assert (first.scanned, first.added) == (2, 2)
    second = env.services.deadlines.scan_stored_mail()
    assert (second.scanned, second.failed, second.added) == (0, 0, 0)
    assert len(env.deadlines()) == 2


def test_a_deadline_found_by_the_hook_is_not_duplicated_by_the_scan() -> None:
    env = make_env()
    env.deliver(mail_message("m1"))
    env.db.execute("DELETE FROM mail_deadline_scans")  # as if it had never been marked
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.added) == (1, 0)
    assert len(env.deadlines()) == 1


def test_model_failure_leaves_the_message_unscanned_and_the_next_run_retries() -> None:
    model = FakeModel(LLMUnavailable("down"))
    env = make_env(llm=model)
    _stored(env, "m1", 2, body=NEEDS_MODEL)
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.failed, result.added) == (0, 1, 0)
    assert _scanned_ids(env) == set() and env.deadlines() == []

    model.reply = FRIDAY_REPLY
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.failed, result.added) == (1, 0, 1)
    assert _scanned_ids(env) == {"m1"} and model.calls == 2
    assert [d.found_by for d in env.deadlines()] == ["llm"]


def test_an_unparseable_reply_is_a_failure_too() -> None:
    env = make_env(llm=FakeModel("garbage"))
    _stored(env, "m1", 2, body=NEEDS_MODEL)
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.failed) == (0, 1)
    assert _scanned_ids(env) == set()


def test_a_reply_with_no_deadline_counts_as_scanned() -> None:
    env = make_env(llm=FakeModel('{"deadlines": []}'))
    _stored(env, "m1", 2, body=NEEDS_MODEL)
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.failed, result.added) == (1, 0, 0)


def test_the_run_stops_after_consecutive_model_failures() -> None:
    model = FakeModel(LLMUnavailable("down"))
    env = make_env(llm=model)
    for i in range(MAIL_SCAN_MAX_FAILURES + 3):
        _stored(env, f"m{i}", 1 + i * 0.1, body=NEEDS_MODEL)
    result = env.services.deadlines.scan_stored_mail()
    assert result.failed == MAIL_SCAN_MAX_FAILURES == model.calls
    assert result.scanned == 0


def test_a_failure_does_not_stop_the_messages_around_it() -> None:
    class Flaky:
        calls = 0

        def complete(self, messages: Any, tools: Any) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                raise LLMUnavailable("blip")
            return LLMResponse(from_model(FRIDAY_REPLY), [])

    env = make_env(llm=Flaky())
    _stored(env, "newest", 1, body=NEEDS_MODEL)
    _stored(env, "next", 2, body="Fee due 2026-10-14")
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.failed, result.added) == (1, 1, 1)
    assert _scanned_ids(env) == {"next"}


def test_each_run_is_capped_and_newest_first() -> None:
    env = make_env()
    for i in range(5):
        _stored(env, f"m{i}", 1 + i, body=f"Fee due 2026-10-1{i}")
    first = env.services.deadlines.scan_stored_mail(limit=2)
    assert first.scanned == 2
    assert _scanned_ids(env) == {"m0", "m1"}
    env.services.deadlines.scan_stored_mail(limit=2)
    env.services.deadlines.scan_stored_mail(limit=2)
    assert _scanned_ids(env) == {f"m{i}" for i in range(5)}
    assert env.services.deadlines.scan_stored_mail(limit=2).scanned == 0
    assert MAIL_SCAN_LIMIT == 200


def test_mail_the_rules_skip_is_recorded_so_it_cannot_starve_the_cap() -> None:
    env = make_env()
    _stored(env, "promo", 1)
    env.mail.set_category(ME, "promo", "promo", "rule", "test")
    _stored(env, "spam-label", 2, label_ids=("INBOX", "SPAM"))
    _stored(env, "real", 3)
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.added) == (3, 1)
    assert _scanned_ids(env) == {"promo", "spam-label", "real"}


def test_deleted_mail_is_not_scanned() -> None:
    env = make_env()
    _stored(env, "gone", 1)
    env.mail.mark_deleted(ME, "gone")
    assert env.services.deadlines.scan_stored_mail().scanned == 0


def test_the_hook_marks_what_it_handled_and_leaves_failures_and_old_mail() -> None:
    model = FakeModel(LLMUnavailable("down"))
    env = make_env(llm=model, deadline_horizon_days=14)
    env.deliver(mail_message("ok", body="Fee due 2026-10-12"))
    env.deliver(mail_message("fails", body=NEEDS_MODEL))
    env.deliver(mail_message("old", body="Fee due 2026-10-12", internal_date=_ms(env, days=20)))
    assert _scanned_ids(env) == {"ok"}
    assert model.calls == 1
    model.reply = FRIDAY_REPLY
    result = env.services.deadlines.scan_stored_mail()
    assert result.scanned == 2  # the failed one and the one past the 14-day horizon
    assert model.calls == 2  # only the failed one needed the model again
    assert _scanned_ids(env) == {"ok", "fails", "old"}


def test_the_model_only_ever_sees_redacted_text() -> None:
    class Recording:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, messages: Sequence[ChatMessage], tools: Any) -> LLMResponse:
            self.prompts.extend(m.content.text for m in messages)
            return LLMResponse(from_model('{"deadlines": []}'), [])

    model = Recording()
    env = make_env(llm=model)
    _stored(env, "m1", 2, body=f"{NEEDS_MODEL} Reply to {ME} about account 123456789012.")
    env.services.deadlines.scan_stored_mail()
    assert model.prompts
    joined = "\n".join(model.prompts)
    assert ME not in joined and "123456789012" not in joined


def test_scan_never_touches_the_calendar_or_the_registry() -> None:
    env = make_env()
    _stored(env, "m1", 2)
    tools_before = env.registry.names()
    env.services.deadlines.scan_stored_mail()
    assert env.calendar.inserted == [] and env.calendar.deleted == []
    assert env.db.query("SELECT * FROM auto_events") == []
    assert env.db.query("SELECT * FROM pending_actions") == []
    assert env.registry.names() == tools_before


def test_scan_logs_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    env = make_env()
    _stored(env, "m1", 2, subject="Secret scholarship", body="Fee due 2026-10-12 from Registrar")
    with caplog.at_level(logging.INFO, logger="agent"):
        env.services.deadlines.scan_stored_mail()
    assert "scanned=1 failed=0 added=1" in caplog.text
    assert "Secret" not in caplog.text and "example" not in caplog.text


def test_scan_without_a_mail_store_does_nothing() -> None:
    env = make_env()
    collector = env.services.deadlines
    collector._mail = None
    result = collector.scan_stored_mail()
    assert (result.scanned, result.failed, result.added) == (0, 0, 0)


def test_ignored_senders_never_produce_deadlines() -> None:
    env = make_env(deadline_ignore_senders=("example.net", "alerts@example.com"))
    env.deliver(mail_message("domain", from_addr="noreply@example.net"))
    env.deliver(mail_message("subdomain", from_addr="news@mail.example.net"))
    env.deliver(mail_message("address", from_addr="alerts@example.com"))
    env.deliver(mail_message("kept", from_addr="registrar@example.org"))
    keys = sorted(r["source_id"] for r in env.db.query("SELECT source_id FROM deadlines"))
    assert keys == ["kept"]


def test_ignore_senders_setting_is_parsed() -> None:
    from agent.config import Settings

    settings = Settings.from_env(
        {"PERSONALAI_DEADLINE_IGNORE_SENDERS": "example.net, a@b.example.com"}
    )
    assert settings.deadline_ignore_senders == ("example.net", "a@b.example.com")
