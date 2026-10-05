"""Runtime settings. Secrets are never read from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _split_paths(value: str) -> tuple[str, ...]:
    """``os.pathsep``-separated (``;`` on Windows), so paths may contain commas."""
    return tuple(part.strip() for part in value.split(os.pathsep) if part.strip())


@dataclass(frozen=True)
class Settings:
    bind_hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = 8765
    db_path: Path = Path.home() / ".personalai" / "agent.db"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "qwen2.5:3b"
    owner_emails: tuple[str, ...] = ()
    mail_accounts: tuple[str, ...] = ()
    vip_senders: tuple[str, ...] = ()
    college_domains: tuple[str, ...] = ()
    mail_poll_minutes: int = 5
    mail_initial_days: int = 7
    classifier_model: str = "qwen2.5:3b"
    pairing_window_seconds: int = 300
    max_agent_steps: int = 6
    calendar_accounts: tuple[str, ...] = ()
    classroom_accounts: tuple[str, ...] = ()
    drive_accounts: tuple[str, ...] = ()
    deadline_calendar_account: str | None = None
    deadline_poll_minutes: int = 60
    deadline_horizon_days: int = 14
    file_roots: tuple[str, ...] = ()
    file_index_minutes: int = 30
    finance_utc_offset_minutes: int = 330
    finance_categorize_minutes: int = 15

    @property
    def google_accounts(self) -> tuple[str, ...]:
        """Every Google account any connector uses, lower-cased and de-duplicated."""
        return tuple(
            dict.fromkeys(
                a.lower()
                for a in (
                    *self.mail_accounts,
                    *self.calendar_accounts,
                    *self.classroom_accounts,
                    *self.drive_accounts,
                )
            )
        )

    @property
    def deadline_calendar(self) -> str | None:
        """The calendar that receives proposed Classroom deadlines (default: first calendar)."""
        if self.deadline_calendar_account:
            return self.deadline_calendar_account
        return self.calendar_accounts[0] if self.calendar_accounts else None

    @property
    def redaction_emails(self) -> tuple[str, ...]:
        """Every address the owner uses, lower-cased and de-duplicated."""
        return tuple(dict.fromkeys(a.lower() for a in (*self.owner_emails, *self.google_accounts)))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        defaults = cls()
        return cls(
            bind_hosts=_split(e["PERSONALAI_BIND_HOSTS"])
            if "PERSONALAI_BIND_HOSTS" in e
            else defaults.bind_hosts,
            port=int(e.get("PERSONALAI_PORT", defaults.port)),
            db_path=Path(e["PERSONALAI_DB_PATH"])
            if "PERSONALAI_DB_PATH" in e
            else defaults.db_path,
            nvidia_model=e.get("PERSONALAI_NVIDIA_MODEL", defaults.nvidia_model),
            owner_emails=_split(e.get("PERSONALAI_OWNER_EMAILS", "")),
            mail_accounts=_split(e.get("PERSONALAI_MAIL_ACCOUNTS", "")),
            vip_senders=_split(e.get("PERSONALAI_VIP_SENDERS", "")),
            college_domains=_split(e.get("PERSONALAI_COLLEGE_DOMAINS", "")),
            mail_poll_minutes=int(
                e.get("PERSONALAI_MAIL_POLL_MINUTES", defaults.mail_poll_minutes)
            ),
            mail_initial_days=int(
                e.get("PERSONALAI_MAIL_INITIAL_DAYS", defaults.mail_initial_days)
            ),
            classifier_model=e.get("PERSONALAI_CLASSIFIER_MODEL", defaults.classifier_model),
            calendar_accounts=_split(e.get("PERSONALAI_CALENDAR_ACCOUNTS", "")),
            classroom_accounts=_split(e.get("PERSONALAI_CLASSROOM_ACCOUNTS", "")),
            drive_accounts=_split(e.get("PERSONALAI_DRIVE_ACCOUNTS", "")),
            deadline_calendar_account=e.get("PERSONALAI_DEADLINE_CALENDAR") or None,
            deadline_poll_minutes=int(
                e.get("PERSONALAI_DEADLINE_POLL_MINUTES", defaults.deadline_poll_minutes)
            ),
            deadline_horizon_days=int(
                e.get("PERSONALAI_DEADLINE_HORIZON_DAYS", defaults.deadline_horizon_days)
            ),
            file_roots=_split_paths(e.get("PERSONALAI_FILE_ROOTS", "")),
            file_index_minutes=int(
                e.get("PERSONALAI_FILE_INDEX_MINUTES", defaults.file_index_minutes)
            ),
            finance_utc_offset_minutes=int(
                e.get("PERSONALAI_FINANCE_UTC_OFFSET_MINUTES", defaults.finance_utc_offset_minutes)
            ),
            finance_categorize_minutes=int(
                e.get("PERSONALAI_FINANCE_CATEGORIZE_MINUTES", defaults.finance_categorize_minutes)
            ),
        )
