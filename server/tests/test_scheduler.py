from __future__ import annotations

import threading
from typing import Any

from agent.scheduler import MAIL_JOB_ID, create_mail_scheduler, start_mail_polling


class FakeSync:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.called = threading.Event()

    def sync_all(self, accounts: Any) -> dict[str, Any]:
        self.calls.append(list(accounts))
        self.called.set()
        return {}


def test_job_is_registered_with_safe_options_and_runs_sync_all() -> None:
    sync = FakeSync()
    scheduler = create_mail_scheduler(sync, ["a@example.com"], 5)  # type: ignore[arg-type]
    job = scheduler.get_job(MAIL_JOB_ID)
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.trigger.interval.total_seconds() == 300
    assert str(scheduler.timezone) == "UTC"
    assert job.next_run_time is not None or scheduler.state == 0
    job.func()
    assert sync.calls == [["a@example.com"]]


def test_started_scheduler_syncs_immediately_and_shuts_down() -> None:
    sync = FakeSync()
    scheduler = start_mail_polling(sync, ["a@example.com"], 60)  # type: ignore[arg-type]
    try:
        assert sync.called.wait(5)
    finally:
        scheduler.shutdown(wait=False)
    assert not scheduler.running
