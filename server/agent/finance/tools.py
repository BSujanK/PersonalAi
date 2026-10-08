"""Finance tools. All READ, and they return aggregates only: no rows, references or raw SMS."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from agent.core.clock import Clock
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.finance.categorize import CATEGORIES
from agent.finance.store import UNCATEGORIZED, FinanceStore, StoredTxn
from agent.finance.summary import (
    GROUP_BYS,
    PERIODS,
    DateRange,
    format_inr,
    group_transactions,
    local_tz,
    resolve_period,
    spend_summary,
)

MAX_GROUPS = 20
MAX_INR = Decimal(10**9)
_CATEGORY_VALUES = (*CATEGORIES, UNCATEGORIZED)
_BALANCE_NOTE = "Latest figure reported by the bank; balances are never estimated."

_PERIOD_PROPS: dict[str, Any] = {
    "period": {"type": "string", "enum": list(PERIODS)},
    "from": {"type": "string", "format": "date", "description": "First day, YYYY-MM-DD."},
    "to": {"type": "string", "format": "date", "description": "Last day, YYYY-MM-DD, inclusive."},
}


def _check_str(value: Any, name: str, max_len: int) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= max_len:
        raise ValueError(f"{name} must be a string of 1 to {max_len} characters")
    return value


def _check_enum(value: Any, allowed: tuple[str, ...], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}")
    return value


def _check_date(value: Any, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be a YYYY-MM-DD date") from None


def _check_inr(value: Any, name: str) -> int:
    """Rupees (number) to paise."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number of rupees")
    try:
        rupees = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{name} must be a number of rupees") from None
    if not 0 <= rupees <= MAX_INR:
        raise ValueError(f"{name} must be between 0 and {MAX_INR}")
    return int(rupees * 100)


def _check_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_GROUPS:
        raise ValueError(f"limit must be an integer between 1 and {MAX_GROUPS}")
    return value


def _reject_unknown(args: dict[str, Any], allowed: set[str]) -> None:
    extra = set(args) - allowed
    if extra:
        raise ValueError(f"unexpected arguments: {', '.join(sorted(extra))}")


def _period(args: dict[str, Any], now: datetime, offset_minutes: int) -> DateRange:
    """The requested window; this month when none is given."""
    if not {"period", "from", "to"} & set(args):
        return resolve_period(now, offset_minutes, "this_month")
    start = _check_date(args["from"], "from") if "from" in args else None
    end = _check_date(args["to"], "to") if "to" in args else None
    period = _check_enum(args["period"], PERIODS, "period") if "period" in args else None
    return resolve_period(now, offset_minutes, period, start, end)


def _period_info(window: DateRange) -> dict[str, str]:
    return {"from": window.first.isoformat(), "to": window.last.isoformat()}


def _matches(txn: StoredTxn, account: str | None, counterparty: str | None) -> bool:
    if account is not None:
        mask = (txn.account_mask or "").lower()
        wanted = account.lower()
        if not (mask == wanted or (len(wanted) <= 4 and mask.endswith(wanted))):
            return False
    return counterparty is None or counterparty.lower() in (txn.counterparty or "").lower()


def register_finance_tools(
    registry: ToolRegistry, store: FinanceStore, clock: Clock, offset_minutes: int
) -> None:
    def spend(args: dict[str, Any]) -> Any:
        _reject_unknown(args, {*_PERIOD_PROPS, "category"})
        window = _period(args, clock(), offset_minutes)
        category = (
            _check_enum(args["category"], _CATEGORY_VALUES, "category")
            if "category" in args
            else None
        )
        txns = store.txns_between(window.start, window.end, category=category)
        return {**_period_info(window), **spend_summary(txns)}

    def balances(args: dict[str, Any]) -> Any:
        _reject_unknown(args, set())
        tz = local_tz(offset_minutes)
        return {
            "note": _BALANCE_NOTE,
            "accounts": [
                {
                    "bank": b.bank,
                    "account": b.account_mask,
                    "balance_inr": format_inr(b.balance_paise),
                    "as_of": b.as_of.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                    "source": b.source,
                }
                for b in store.list_balances()
            ],
        }

    def transactions(args: dict[str, Any]) -> Any:
        _reject_unknown(
            args,
            {
                *_PERIOD_PROPS,
                "direction",
                "category",
                "account",
                "counterparty",
                "min_inr",
                "max_inr",
                "group_by",
                "limit",
            },
        )
        window = _period(args, clock(), offset_minutes)
        direction = _check_enum(args.get("direction", "debit"), ("debit", "credit"), "direction")
        category = (
            _check_enum(args["category"], _CATEGORY_VALUES, "category")
            if "category" in args
            else None
        )
        account = _check_str(args["account"], "account", 20) if "account" in args else None
        counterparty = (
            _check_str(args["counterparty"], "counterparty", 50) if "counterparty" in args else None
        )
        low = _check_inr(args["min_inr"], "min_inr") if "min_inr" in args else None
        high = _check_inr(args["max_inr"], "max_inr") if "max_inr" in args else None
        if low is not None and high is not None and low > high:
            raise ValueError("min_inr must not exceed max_inr")
        group_by = _check_enum(args.get("group_by", "category"), GROUP_BYS, "group_by")
        limit = _check_limit(args.get("limit", 10))
        txns = [
            t
            for t in store.txns_between(
                window.start, window.end, direction=direction, category=category
            )
            if _matches(t, account, counterparty)
            and (low is None or t.amount_paise >= low)
            and (high is None or t.amount_paise <= high)
        ]
        return {
            **_period_info(window),
            "direction": direction,
            "group_by": group_by,
            **group_transactions(txns, group_by, offset_minutes, limit),
        }

    def overview(args: dict[str, Any]) -> Any:
        _reject_unknown(args, set())
        return {"balances": balances({}), "this_month": spend({"period": "this_month"})}

    registry.register(
        Tool(
            name="spend_summary",
            description=(
                "Spending summary for a period: total spent, received and net, spend by "
                "category and the top merchants. Amounts are in rupees. unrecorded_inr is the "
                "part of the spending inferred from balance gaps (payments the bank sent no "
                "message for); it is already included in the totals."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **_PERIOD_PROPS,
                    "category": {"type": "string", "enum": list(_CATEGORY_VALUES)},
                },
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=spend,
        )
    )
    registry.register(
        Tool(
            name="balances",
            description=(
                "Account balances as last reported by the bank's messages, with the time of the "
                "report. These are reported figures, not estimates."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            kind=ToolKind.READ,
            run=balances,
        )
    )
    registry.register(
        Tool(
            name="transactions",
            description=(
                "Aggregate transactions for a period into groups (count and total in rupees), "
                "filtered by direction, category, account, merchant or amount. Debits by default. "
                "unrecorded_inr is the part of the debits inferred from balance gaps; it is "
                "already included in the totals."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **_PERIOD_PROPS,
                    "direction": {"type": "string", "enum": ["debit", "credit"]},
                    "category": {"type": "string", "enum": list(_CATEGORY_VALUES)},
                    "account": {"type": "string", "maxLength": 20},
                    "counterparty": {"type": "string", "maxLength": 50},
                    "min_inr": {"type": "number", "minimum": 0},
                    "max_inr": {"type": "number", "minimum": 0},
                    "group_by": {"type": "string", "enum": list(GROUP_BYS)},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_GROUPS},
                },
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=transactions,
        )
    )
    registry.register(
        Tool(
            name="account_overview",
            description=(
                "Account balances as last reported by the bank's messages plus this month's "
                "spending summary, in one call. Aggregates only, amounts in rupees."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            kind=ToolKind.READ,
            run=overview,
        )
    )
