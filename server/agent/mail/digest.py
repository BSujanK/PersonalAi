"""Digest of recent mail: important items plus per-category counts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agent.mail.rules import CATEGORY_VALUES
from agent.mail.store import MailStore

MAX_IMPORTANT = 20
_SCAN_LIMIT = 5000


@dataclass(frozen=True)
class DigestItem:
    account: str
    id: str
    from_name: str
    from_addr: str
    subject: str
    snippet: str
    reason: str | None
    received: str  # ISO 8601, UTC


@dataclass(frozen=True)
class Digest:
    important: list[DigestItem]
    counts: dict[str, int]
    unclassified: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def build_digest(store: MailStore, now: datetime, hours: int = 24) -> Digest:
    since_ms = int((now - timedelta(hours=hours)).timestamp() * 1000)
    counts: dict[str, int] = dict.fromkeys(CATEGORY_VALUES, 0)
    unclassified = 0
    important: list[DigestItem] = []
    for mail in store.recent(since_ms, limit=_SCAN_LIMIT):  # newest first
        if mail.category is None:
            unclassified += 1
            continue
        counts[mail.category] += 1
        if mail.category == "important" and len(important) < MAX_IMPORTANT:
            important.append(
                DigestItem(
                    account=mail.account,
                    id=mail.id,
                    from_name=mail.from_name,
                    from_addr=mail.from_addr,
                    subject=mail.subject,
                    snippet=mail.snippet,
                    reason=mail.reason,
                    received=datetime.fromtimestamp(mail.internal_date / 1000, UTC).isoformat(),
                )
            )
    return Digest(important, counts, unclassified)
