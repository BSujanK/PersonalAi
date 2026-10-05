"""Background polling for mail sync."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from agent.mail.sync import MailSync

MAIL_JOB_ID = "mail_poll"


def create_mail_scheduler(
    sync: MailSync, accounts: Sequence[str], minutes: int
) -> BackgroundScheduler:
    """Build (but do not start) a scheduler that syncs every account, first run immediately."""
    scheduler = BackgroundScheduler(timezone="UTC")

    def poll() -> None:
        sync.sync_all(accounts)

    scheduler.add_job(
        poll,
        "interval",
        minutes=minutes,
        id=MAIL_JOB_ID,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    return scheduler


def start_mail_polling(
    sync: MailSync, accounts: Sequence[str], minutes: int
) -> BackgroundScheduler:
    scheduler = create_mail_scheduler(sync, accounts, minutes)
    scheduler.start()
    return scheduler
