"""Pure period math and aggregation over transactions. Amounts leave here as rupee strings."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Literal, get_args

from agent.finance.store import UNCATEGORIZED, StoredTxn

Period = Literal[
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "last_7_days",
    "last_30_days",
    "this_year",
]
PERIODS: tuple[str, ...] = get_args(Period)
GroupBy = Literal["category", "counterparty", "day", "week", "month", "account", "channel"]
GROUP_BYS: tuple[str, ...] = get_args(GroupBy)

MAX_RANGE_DAYS = 366
TOP_COUNTERPARTIES = 5
NAME_CHARS = 40


@dataclass(frozen=True)
class DateRange:
    """A half-open UTC interval plus the local calendar dates it covers (``last`` inclusive)."""

    start: datetime
    end: datetime
    first: date
    last: date


def local_tz(offset_minutes: int) -> timezone:
    return timezone(timedelta(minutes=offset_minutes))


def _range(first: date, after_last: date, offset_minutes: int) -> DateRange:
    tz = local_tz(offset_minutes)
    return DateRange(
        datetime.combine(first, time.min, tz).astimezone(UTC),
        datetime.combine(after_last, time.min, tz).astimezone(UTC),
        first,
        after_last - timedelta(days=1),
    )


def _month_start(day: date, back: int = 0) -> date:
    index = day.year * 12 + day.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def resolve_period(
    now: datetime,
    offset_minutes: int,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> DateRange:
    """Resolve a named period or an inclusive ``start``..``end`` date range in local time."""
    if period is not None and (start is not None or end is not None):
        raise ValueError("give either period or from/to, not both")
    if period is None:
        if start is None or end is None:
            raise ValueError("period or both from and to are required")
        if end < start:
            raise ValueError("to must not be before from")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"date range must be at most {MAX_RANGE_DAYS} days")
        return _range(start, end + timedelta(days=1), offset_minutes)
    today = now.astimezone(local_tz(offset_minutes)).date()
    week = today - timedelta(days=today.weekday())
    if period == "today":
        return _range(today, today + timedelta(days=1), offset_minutes)
    if period == "yesterday":
        return _range(today - timedelta(days=1), today, offset_minutes)
    if period == "this_week":
        return _range(week, week + timedelta(days=7), offset_minutes)
    if period == "last_week":
        return _range(week - timedelta(days=7), week, offset_minutes)
    if period == "this_month":
        return _range(_month_start(today), _month_start(today, -1), offset_minutes)
    if period == "last_month":
        return _range(_month_start(today, 1), _month_start(today), offset_minutes)
    if period == "last_7_days":
        return _range(today - timedelta(days=6), today + timedelta(days=1), offset_minutes)
    if period == "last_30_days":
        return _range(today - timedelta(days=29), today + timedelta(days=1), offset_minutes)
    if period == "this_year":
        return _range(date(today.year, 1, 1), date(today.year + 1, 1, 1), offset_minutes)
    raise ValueError(f"unknown period: {period}")


def format_inr(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    return f"{sign}{rupees}.{rest:02d}"


def _name(text: str) -> str:
    return " ".join(text.split())[:NAME_CHARS]


def _spend_by(txns: list[StoredTxn], key: str) -> list[dict[str, int | str]]:
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for txn in txns:
        if txn.direction != "debit":
            continue
        label = (
            (txn.category or UNCATEGORIZED) if key == "category" else _name(txn.counterparty or "")
        )
        if not label:
            continue
        totals[label] += txn.amount_paise
        counts[label] += 1
    ranked = sorted(totals, key=lambda k: (-totals[k], k))
    return [{"key": k, "paise": totals[k], "count": counts[k]} for k in ranked]


def unrecorded_inr(txns: list[StoredTxn]) -> str:
    """Debits inferred from balance gaps: real money out that no message reported."""
    return format_inr(sum(t.amount_paise for t in txns if t.inferred and t.direction == "debit"))


def spend_summary(txns: list[StoredTxn]) -> dict[str, object]:
    spent = sum(t.amount_paise for t in txns if t.direction == "debit")
    received = sum(t.amount_paise for t in txns if t.direction == "credit")
    by_category = _spend_by(txns, "category")
    top = _spend_by(txns, "counterparty")[:TOP_COUNTERPARTIES]
    return {
        "count": len(txns),
        "spent_inr": format_inr(spent),
        "received_inr": format_inr(received),
        "net_inr": format_inr(received - spent),
        "unrecorded_inr": unrecorded_inr(txns),
        "by_category": [
            {"category": g["key"], "total_inr": format_inr(int(g["paise"])), "count": g["count"]}
            for g in by_category
        ],
        "top_counterparties": [
            {"name": g["key"], "total_inr": format_inr(int(g["paise"])), "count": g["count"]}
            for g in top
        ],
    }


def _group_key(txn: StoredTxn, group_by: str, offset_minutes: int) -> str:
    local = txn.occurred_at.astimezone(local_tz(offset_minutes)).date()
    if group_by == "category":
        return txn.category or UNCATEGORIZED
    if group_by == "counterparty":
        return _name(txn.counterparty or "") or "unknown"
    if group_by == "day":
        return local.isoformat()
    if group_by == "week":
        return (local - timedelta(days=local.weekday())).isoformat()
    if group_by == "month":
        return local.strftime("%Y-%m")
    if group_by == "account":
        return f"{txn.bank} {txn.account_mask}" if txn.account_mask else txn.bank
    return txn.channel


def group_transactions(
    txns: list[StoredTxn], group_by: str, offset_minutes: int, limit: int
) -> dict[str, object]:
    """Groups of {key, count, total_inr} plus overall figures. Never individual rows."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for txn in txns:
        key = _group_key(txn, group_by, offset_minutes)
        totals[key] += txn.amount_paise
        counts[key] += 1
    if group_by in ("day", "week", "month"):
        keys = sorted(totals)
    else:
        keys = sorted(totals, key=lambda k: (-totals[k], k))
    return {
        "count": len(txns),
        "total_inr": format_inr(sum(totals.values())),
        "unrecorded_inr": unrecorded_inr(txns),
        "group_count": len(keys),
        "groups": [
            {"key": k, "count": counts[k], "total_inr": format_inr(totals[k])} for k in keys[:limit]
        ],
    }
