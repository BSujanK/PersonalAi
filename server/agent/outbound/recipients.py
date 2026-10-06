"""Recipient checks shared by mail_send, mail_reply and drive_share."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from agent.config import Settings
from agent.core.tools import ActionRejected

MAX_RECIPIENTS = 50
# Free mail providers: sharing one with the owner does not make an address "internal".
PUBLIC_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.co.in",
        "ymail.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "zoho.com",
        "rediffmail.com",
    }
)
_ADDRESS = re.compile(
    r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)
_BIDI = re.compile("[‪-‮⁦-⁩‎‏؜]")

SentLookup = Callable[[str], bool]


def check_address(value: Any) -> str:
    """A plain address (no display name), lower-cased. Raises ``ActionRejected``."""
    if not isinstance(value, str):
        raise ActionRejected("each email address must be a string")
    addr = value.strip().lower()
    if len(addr) > 254 or not _ADDRESS.fullmatch(addr):
        raise ActionRejected("invalid email address; give a plain address like name@example.com")
    return addr


def check_addresses(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_RECIPIENTS:
        raise ActionRejected(f"{name} must be a list of at most {MAX_RECIPIENTS} addresses")
    return list(dict.fromkeys(check_address(v) for v in value))


def check_text(value: Any, name: str, max_len: int, *, single_line: bool) -> str:
    """Text that goes out as-is. Bidi controls are refused so the preview cannot be disguised."""
    if not isinstance(value, str) or len(value) > max_len:
        raise ActionRejected(f"{name} must be a string of at most {max_len} characters")
    if _BIDI.search(value):
        raise ActionRejected(f"{name} contains text-direction control characters")
    if single_line and any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ActionRejected(f"{name} must be a single line")
    return value


def display(text: str, limit: int = 200) -> str:
    """One preview line for untrusted text (file names, subjects): no control or format chars."""
    visible = "".join(
        " " if cat == "Cc" else ch for ch in text if (cat := unicodedata.category(ch)) != "Cf"
    )
    return " ".join(visible.split())[:limit]


def domain_of(addr: str) -> str:
    return addr.rpartition("@")[2]


@dataclass(frozen=True)
class RecipientPolicy:
    """Flags each recipient: the owner's own address, NEW (never in sent mail), EXTERNAL."""

    owner_addresses: frozenset[str]
    owner_domains: frozenset[str]
    sent_to: SentLookup | None = None

    @classmethod
    def from_settings(cls, settings: Settings, sent_to: SentLookup | None) -> RecipientPolicy:
        owners = frozenset(settings.redaction_emails)
        domains = {domain_of(a) for a in owners} - PUBLIC_DOMAINS
        domains |= {d.strip().lower().lstrip("@") for d in settings.college_domains}
        return cls(owners, frozenset(d for d in domains if d), sent_to)

    def _seen(self, addr: str) -> bool:
        if self.sent_to is None:
            return False
        try:
            return self.sent_to(addr)
        except Exception:  # an unreachable mailbox must not hide the warning
            return False

    def classify(self, addr: str, field: str) -> dict[str, Any]:
        you = addr in self.owner_addresses
        return {
            "field": field,
            "addr": addr,
            "you": you,
            "new": not you and not self._seen(addr),
            "external": not you and domain_of(addr) not in self.owner_domains,
        }


def flags(entry: dict[str, Any]) -> str:
    if entry["you"]:
        return "(you)"
    marks = [m for m, on in (("NEW", entry["new"]), ("EXTERNAL", entry["external"])) if on]
    return "⚠ " + " · ".join(marks) if marks else "(you have emailed them before)"


def recipient_lines(entries: Iterable[dict[str, Any]], field: str) -> list[str]:
    chosen = [e for e in entries if e["field"] == field]
    if not chosen:
        return [f"{field}: (none)"]
    return [f"{field}:"] + [f"  • {e['addr']}  {flags(e)}" for e in chosen]


def warning_lines(entries: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    new = sum(1 for e in entries if e["new"])
    external = sum(1 for e in entries if e["external"])
    if new:
        lines.append(f"⚠ {new} recipient(s) you have never emailed (NEW).")
    if external:
        lines.append(f"⚠ {external} recipient(s) outside your own domains (EXTERNAL).")
    return lines
