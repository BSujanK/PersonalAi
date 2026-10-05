from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

import pytest

from agent.finance.store import StoredTxn
from agent.finance.summary import (
    format_inr,
    group_transactions,
    resolve_period,
    spend_summary,
)
from tests.finance_support import make_fin, txn

IST = 330
# Monday 2026-10-05 00:30 IST is still Sunday 2026-10-04 in UTC.
NOW = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)  # 2026-10-05 00:30 IST


def _utc(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("today", _utc(2026, 10, 4, 18, 30), _utc(2026, 10, 5, 18, 30)),
        ("yesterday", _utc(2026, 10, 3, 18, 30), _utc(2026, 10, 4, 18, 30)),
        ("this_week", _utc(2026, 10, 4, 18, 30), _utc(2026, 10, 11, 18, 30)),
        ("last_week", _utc(2026, 9, 27, 18, 30), _utc(2026, 10, 4, 18, 30)),
        ("this_month", _utc(2026, 9, 30, 18, 30), _utc(2026, 10, 31, 18, 30)),
        ("last_month", _utc(2026, 8, 31, 18, 30), _utc(2026, 9, 30, 18, 30)),
        ("last_7_days", _utc(2026, 9, 28, 18, 30), _utc(2026, 10, 5, 18, 30)),
        ("last_30_days", _utc(2026, 9, 5, 18, 30), _utc(2026, 10, 5, 18, 30)),
        ("this_year", _utc(2025, 12, 31, 18, 30), _utc(2026, 12, 31, 18, 30)),
    ],
)
def test_named_periods_in_ist(period: str, start: datetime, end: datetime) -> None:
    window = resolve_period(NOW, IST, period)
    assert (window.start, window.end) == (start, end)


def test_week_starts_on_monday_and_utc_clock_would_differ() -> None:
    assert resolve_period(NOW, IST, "this_week").first == date(2026, 10, 5)
    assert resolve_period(NOW, 0, "this_week").first == date(2026, 9, 28)


def test_month_rollover_at_year_end() -> None:
    now = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)
    assert resolve_period(now, IST, "last_month").first == date(2025, 12, 1)
    assert resolve_period(datetime(2026, 12, 15, tzinfo=UTC), IST, "this_month").last == date(
        2026, 12, 31
    )


def test_explicit_range_is_inclusive_and_validated() -> None:
    window = resolve_period(NOW, IST, None, date(2026, 10, 1), date(2026, 10, 2))
    assert (window.start, window.end) == (_utc(2026, 9, 30, 18, 30), _utc(2026, 10, 2, 18, 30))
    assert (window.first, window.last) == (date(2026, 10, 1), date(2026, 10, 2))
    resolve_period(NOW, IST, None, date(2026, 1, 1), date(2026, 12, 31))  # 365 days
    with pytest.raises(ValueError, match="366"):
        resolve_period(NOW, IST, None, date(2024, 1, 1), date(2025, 1, 1))
    with pytest.raises(ValueError):
        resolve_period(NOW, IST, None, date(2026, 10, 2), date(2026, 10, 1))
    with pytest.raises(ValueError):
        resolve_period(NOW, IST, None, date(2026, 10, 2), None)
    with pytest.raises(ValueError):
        resolve_period(NOW, IST, "today", date(2026, 10, 2), date(2026, 10, 3))
    with pytest.raises(ValueError):
        resolve_period(NOW, IST, "fortnight")


def test_ist_boundary_selects_rows() -> None:
    env = make_fin()
    inside = _utc(2026, 10, 4, 18, 31)  # 00:01 IST on the 5th
    before = _utc(2026, 10, 4, 18, 29)  # 23:59 IST on the 4th
    env.ledger.record(txn(reference="1"), inside, "sms")
    env.ledger.record(txn(reference="2"), before, "sms")
    window = resolve_period(NOW, IST, "today")
    assert len(env.store.txns_between(window.start, window.end)) == 1


@pytest.mark.parametrize(
    ("paise", "text"), [(123450, "1234.50"), (5, "0.05"), (0, "0.00"), (-250, "-2.50")]
)
def test_format_inr(paise: int, text: str) -> None:
    assert format_inr(paise) == text


def _sample() -> list[StoredTxn]:
    env = make_fin()
    for i, kw in enumerate(
        [
            {"counterparty": "Swiggy", "amount_paise": 30000},
            {"counterparty": "Swiggy", "amount_paise": 20000},
            {"counterparty": "Test Merchant", "amount_paise": 70000},
            {"counterparty": "ACME SALARY", "direction": "credit", "amount_paise": 5000000},
        ]
    ):
        env.ledger.record(txn(reference=str(i), **kw), _utc(2026, 10, 1 + i, 6), "sms")
    return env.store.txns_between(_utc(2026, 9, 1), _utc(2026, 11, 1))


def test_spend_summary_totals_and_breakdowns() -> None:
    out = spend_summary(_sample())
    assert (out["spent_inr"], out["received_inr"], out["net_inr"], out["count"]) == (
        "1200.00",
        "50000.00",
        "48800.00",
        4,
    )
    assert out["by_category"] == [
        {"category": "uncategorized", "total_inr": "700.00", "count": 1},
        {"category": "food", "total_inr": "500.00", "count": 2},
    ]
    assert out["top_counterparties"] == [
        {"name": "Test Merchant", "total_inr": "700.00", "count": 1},
        {"name": "Swiggy", "total_inr": "500.00", "count": 2},
    ]


def _keys(group_by: str, limit: int = 10) -> list[str]:
    txns = [t for t in _sample() if t.direction == "debit"]
    groups = cast(list[dict[str, str]], group_transactions(txns, group_by, IST, limit)["groups"])
    return [g["key"] for g in groups]


def test_group_by_day_week_month_account_channel() -> None:
    assert _keys("day") == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert _keys("week") == ["2026-09-28"]
    assert _keys("month") == ["2026-10"]
    assert _keys("account") == ["bob XX1234"]
    assert _keys("channel") == ["upi"]


def test_group_limit_keeps_overall_totals() -> None:
    txns = [t for t in _sample() if t.direction == "debit"]
    out = group_transactions(txns, "counterparty", IST, 1)
    assert out["group_count"] == 2 and out["count"] == 3 and out["total_inr"] == "1200.00"
    assert cast(list[object], out["groups"]) == [
        {"key": "Test Merchant", "count": 1, "total_inr": "700.00"}
    ]
