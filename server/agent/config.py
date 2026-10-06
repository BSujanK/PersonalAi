"""Runtime settings. Secrets are never read from the environment."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _split_paths(value: str) -> tuple[str, ...]:
    """``os.pathsep``-separated (``;`` on Windows), so paths may contain commas."""
    return tuple(part.strip() for part in value.split(os.pathsep) if part.strip())


PUSH_MODES = ("off", "expo")


def _push_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in PUSH_MODES:
        raise ValueError("PERSONALAI_PUSH must be 'off' or 'expo'")
    return mode


def _positive_int(name: str, value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return number


MAX_NEWS_FEEDS = 20
MAX_FEED_URL_CHARS = 500
_HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def validate_feed_url(url: str) -> str:
    """A news feed URL: https, a hostname (not an IP literal), no userinfo, port 443 only."""
    if not url or len(url) > MAX_FEED_URL_CHARS:
        raise ValueError(f"a news feed URL must be 1 to {MAX_FEED_URL_CHARS} characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("a news feed URL is malformed") from None
    if parts.scheme != "https" or not host:
        raise ValueError("a news feed URL must be https://")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("a news feed URL must not contain credentials")
    if port not in (None, 443):
        raise ValueError("a news feed URL must use port 443")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return url
    raise ValueError("a news feed URL must use a hostname, not an IP address")


def _news_feeds(value: str) -> tuple[str, ...]:
    feeds = _split(value)
    if len(feeds) > MAX_NEWS_FEEDS:
        raise ValueError(f"PERSONALAI_NEWS_FEEDS allows at most {MAX_NEWS_FEEDS} feeds")
    try:
        return tuple(validate_feed_url(feed) for feed in feeds)
    except ValueError as exc:
        raise ValueError(f"PERSONALAI_NEWS_FEEDS: {exc}") from None


def _flag(value: str, default: bool) -> bool:
    text = value.strip().lower()
    if not text:
        return default
    return text not in ("0", "false", "off", "no")


def _clock_time(value: str) -> str:
    text = value.strip()
    if not _HHMM.fullmatch(text):
        raise ValueError("PERSONALAI_BRIEFING_TIME must be HH:MM (24-hour)")
    return text


@dataclass(frozen=True)
class Settings:
    bind_hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = 8765
    db_path: Path = Path.home() / ".personalai" / "agent.db"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    model_primary: str = ""
    model_fallback: str = ""
    model_long: str = ""
    long_context_tokens: int = 32000
    local_context_tokens: int = 8192  # Ollama's context; longer prompts never go to local
    # Reasoning models (Nemotron, ...) otherwise put their thinking in the reply text.
    cloud_thinking: bool = False
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
    push: str = "off"  # "off" or "expo"; pushes carry only a count, never content
    news_feeds: tuple[str, ...] = ()
    calendar_auto_add: bool = True
    alert_poll_minutes: int = 5
    briefing_time: str = "07:30"

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
            model_primary=e.get("PERSONALAI_MODEL_PRIMARY", defaults.model_primary).strip(),
            model_fallback=e.get("PERSONALAI_MODEL_FALLBACK", defaults.model_fallback).strip(),
            model_long=e.get("PERSONALAI_MODEL_LONG", defaults.model_long).strip(),
            long_context_tokens=_positive_int(
                "PERSONALAI_LONG_CONTEXT_TOKENS",
                e.get("PERSONALAI_LONG_CONTEXT_TOKENS", str(defaults.long_context_tokens)),
            ),
            local_context_tokens=_positive_int(
                "PERSONALAI_LOCAL_CONTEXT_TOKENS",
                e.get("PERSONALAI_LOCAL_CONTEXT_TOKENS", str(defaults.local_context_tokens)),
            ),
            cloud_thinking=e.get("PERSONALAI_CLOUD_THINKING", "").strip().lower()
            in ("1", "true", "on", "yes"),
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
            push=_push_mode(e.get("PERSONALAI_PUSH", defaults.push)),
            news_feeds=_news_feeds(e.get("PERSONALAI_NEWS_FEEDS", "")),
            calendar_auto_add=_flag(
                e.get("PERSONALAI_CALENDAR_AUTO_ADD", ""), defaults.calendar_auto_add
            ),
            alert_poll_minutes=_positive_int(
                "PERSONALAI_ALERT_POLL_MINUTES",
                e.get("PERSONALAI_ALERT_POLL_MINUTES", str(defaults.alert_poll_minutes)),
            ),
            briefing_time=_clock_time(e.get("PERSONALAI_BRIEFING_TIME", defaults.briefing_time)),
        )
