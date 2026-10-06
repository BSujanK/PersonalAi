"""Background jobs: mail sync, Classroom deadlines, alerts, the file index and finance."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)

MAIL_JOB_ID = "mail_poll"
CLASSROOM_DEADLINE_JOB_ID = "classroom_deadlines"
ALERT_JOB_ID = "alerts"
FILE_INDEX_JOB_ID = "file_index"
FINANCE_CATEGORIZE_JOB_ID = "finance_categorize"


@dataclass(frozen=True)
class Job:
    id: str
    run: Callable[[], object]
    minutes: int


def _guarded(job: Job) -> Callable[[], None]:
    """Exceptions are logged by type only: their text can carry paths, addresses or content."""

    def run() -> None:
        try:
            job.run()
        except Exception as exc:
            log.warning("background job %s failed: %s", job.id, type(exc).__name__)

    return run


def create_scheduler(jobs: Sequence[Job]) -> BackgroundScheduler:
    """Build (but do not start) a scheduler running each job on its interval, first run now."""
    scheduler = BackgroundScheduler(timezone="UTC")
    for job in jobs:
        scheduler.add_job(
            _guarded(job),
            "interval",
            minutes=job.minutes,
            id=job.id,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(UTC),
        )
    return scheduler


def start_jobs(jobs: Sequence[Job]) -> BackgroundScheduler | None:
    if not jobs:
        return None
    scheduler = create_scheduler(jobs)
    scheduler.start()
    return scheduler
