from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest

from agent.scheduler import MAIL_JOB_ID, Job, create_scheduler, start_jobs


def test_jobs_are_registered_with_safe_options() -> None:
    calls: list[str] = []
    scheduler = create_scheduler(
        [Job(MAIL_JOB_ID, lambda: calls.append("mail"), 5), Job("other", lambda: None, 60)]
    )
    job = scheduler.get_job(MAIL_JOB_ID)
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.trigger.interval.total_seconds() == 300
    assert str(scheduler.timezone) == "UTC"
    assert scheduler.get_job("other") is not None
    job.func()
    assert calls == ["mail"]


def test_job_exceptions_are_logged_by_type_only(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        raise FileNotFoundError("C:/Users/someone/secret-plan.docx")

    scheduler = create_scheduler([Job("files", boom, 30)])
    job = scheduler.get_job("files")
    assert job is not None
    with caplog.at_level(logging.DEBUG):
        job.func()
    assert "FileNotFoundError" in caplog.text
    assert "secret-plan" not in caplog.text


def test_no_jobs_starts_nothing() -> None:
    assert start_jobs([]) is None


def test_started_scheduler_runs_immediately_and_shuts_down() -> None:
    called = threading.Event()
    scheduler = start_jobs([Job(MAIL_JOB_ID, called.set, 60)])
    assert scheduler is not None
    try:
        assert called.wait(5)
    finally:
        scheduler.shutdown(wait=False)
    assert not scheduler.running


def test_start_delay_postpones_only_the_first_run() -> None:
    before = datetime.now(UTC)
    scheduler = create_scheduler(
        [
            Job("soon", lambda: None, 1440, start_delay_seconds=60),
            Job("now", lambda: None, 5),
        ]
    )
    delayed, immediate = scheduler.get_job("soon"), scheduler.get_job("now")
    assert delayed is not None and immediate is not None
    assert delayed.trigger.interval.total_seconds() == 1440 * 60  # then daily
    assert before + timedelta(seconds=59) <= delayed.next_run_time <= before + timedelta(seconds=70)
    assert immediate.next_run_time <= before + timedelta(seconds=5)
