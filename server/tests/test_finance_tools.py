from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from agent.core.redact import RedactionMap, Redactor
from agent.core.tools import ToolKind, ToolRegistry
from agent.finance.tools import register_finance_tools
from tests.finance_support import FinEnv, balance, make_fin, txn

IST = 330
NOW = datetime(2026, 10, 5, 6, 30, tzinfo=UTC)  # 12:00 IST
REFERENCE = "400011112222"
RAW_SMS = "Rs 1234.50 debited from A/c XX1234 to Test Merchant"


def _setup() -> tuple[ToolRegistry, FinEnv]:
    env = make_fin()
    env.clock.now = NOW
    registry = ToolRegistry()
    register_finance_tools(registry, env.store, env.clock, IST)
    rows = [
        ("Swiggy", 123450, "debit", 3, REFERENCE),
        ("Test Merchant", 50000, "debit", 4, "5001"),
        ("Test Merchant", 25000, "debit", 5, "5002"),
        ("ACME SALARY", 9000000, "credit", 6, "5003"),
    ]
    for name, paise, direction, hour, ref in rows:
        env.ledger.record(
            txn(counterparty=name, amount_paise=paise, direction=direction, reference=ref),
            datetime(2026, 10, 5, hour, 0, tzinfo=UTC),
            "sms",
        )
    env.ledger.record_balance(balance(balance_paise=4567890), NOW, "sms")
    return registry, env


def _run(registry: ToolRegistry, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = registry.get(name)
    assert tool is not None
    result = tool.run(args)
    assert isinstance(result, dict)
    return result


def test_tools_are_read_only_and_untrusted() -> None:
    registry, _ = _setup()
    for name in ("spend_summary", "balances", "transactions", "account_overview"):
        tool = registry.get(name)
        assert tool is not None and tool.kind is ToolKind.READ and tool.untrusted_output
        assert tool.parameters["additionalProperties"] is False


def test_spend_summary_shape() -> None:
    registry, _ = _setup()
    out = _run(registry, "spend_summary", {"period": "today"})
    assert (out["from"], out["to"], out["count"]) == ("2026-10-05", "2026-10-05", 4)
    assert (out["spent_inr"], out["received_inr"]) == ("1984.50", "90000.00")
    assert out["by_category"][0] == {"category": "food", "total_inr": "1234.50", "count": 1}
    assert out["top_counterparties"][0] == {"name": "Swiggy", "total_inr": "1234.50", "count": 1}
    only_food = _run(registry, "spend_summary", {"period": "today", "category": "food"})
    assert only_food["count"] == 1
    assert _run(registry, "spend_summary", {})["from"] == "2026-10-01"  # defaults to this month


def test_balances_report_reported_figure() -> None:
    registry, _ = _setup()
    out = _run(registry, "balances", {})
    assert out["accounts"] == [
        {
            "bank": "bob",
            "account": "XX1234",
            "balance_inr": "45678.90",
            "as_of": "2026-10-05 12:00",
            "source": "sms",
        }
    ]
    assert "never estimated" in out["note"]


def test_account_overview_is_balances_plus_this_month_aggregates() -> None:
    registry, _ = _setup()
    out = _run(registry, "account_overview", {})
    assert set(out) == {"balances", "this_month"}
    assert out["balances"] == _run(registry, "balances", {})
    assert out["this_month"] == _run(registry, "spend_summary", {"period": "this_month"})
    assert (out["this_month"]["from"], out["this_month"]["to"]) == ("2026-10-01", "2026-10-31")
    text = json.dumps(out)
    assert REFERENCE not in text and RAW_SMS not in text  # aggregates only, no ledger rows
    tool = registry.get("account_overview")
    assert tool is not None and tool.parameters["properties"] == {}
    assert tool.parameters["additionalProperties"] is False


def test_transactions_filters_and_groups() -> None:
    registry, _ = _setup()
    out = _run(
        registry,
        "transactions",
        {"period": "today", "counterparty": "test", "group_by": "counterparty"},
    )
    assert out["groups"] == [{"key": "Test Merchant", "count": 2, "total_inr": "750.00"}]
    assert (out["count"], out["total_inr"]) == (2, "750.00")
    credits = _run(registry, "transactions", {"period": "today", "direction": "credit"})
    assert credits["total_inr"] == "90000.00"
    ranged = _run(registry, "transactions", {"period": "today", "min_inr": 300, "max_inr": 1000.5})
    assert ranged["count"] == 1
    assert _run(registry, "transactions", {"period": "today", "account": "1234"})["count"] == 3
    assert _run(registry, "transactions", {"period": "today", "account": "XX9999"})["count"] == 0
    explicit = _run(registry, "transactions", {"from": "2026-10-01", "to": "2026-10-05"})
    assert explicit["count"] == 3


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("spend_summary", {"period": "decade"}),
        ("spend_summary", {"period": "today", "extra": 1}),
        ("spend_summary", {"from": "2026-10-01"}),
        ("spend_summary", {"from": "nope", "to": "2026-10-01"}),
        ("spend_summary", {"from": "2024-01-01", "to": "2026-01-01"}),
        ("spend_summary", {"period": "today", "category": "gold"}),
        ("balances", {"x": 1}),
        ("account_overview", {"x": 1}),
        ("account_overview", {"period": "today"}),
        ("transactions", {"limit": 21}),
        ("transactions", {"limit": 0}),
        ("transactions", {"limit": True}),
        ("transactions", {"group_by": "reference"}),
        ("transactions", {"direction": "sideways"}),
        ("transactions", {"min_inr": -1}),
        ("transactions", {"min_inr": "5"}),
        ("transactions", {"min_inr": 10, "max_inr": 5}),
        ("transactions", {"account": ""}),
        ("transactions", {"counterparty": "x" * 51}),
    ],
)
def test_bad_args_raise_value_error(tool: str, args: dict[str, Any]) -> None:
    registry, _ = _setup()
    with pytest.raises(ValueError):
        _run(registry, tool, args)


def _all_outputs() -> list[dict[str, Any]]:
    registry, _ = _setup()
    calls: list[tuple[str, dict[str, Any]]] = [
        ("spend_summary", {"period": "today"}),
        ("balances", {}),
        ("account_overview", {}),
        *(
            ("transactions", {"period": "today", "group_by": g})
            for g in ("category", "counterparty", "day", "week", "month", "account", "channel")
        ),
    ]
    return [_run(registry, name, args) for name, args in calls]


def test_outputs_survive_redaction_with_amounts_intact() -> None:
    redactor = Redactor()
    for out in _all_outputs():
        text = redactor.redact_structured(out, RedactionMap()).text
        assert json.loads(text).keys() == out.keys()
    spend = redactor.redact_structured(_all_outputs()[0], RedactionMap()).text
    assert "1234.50" in spend and "90000.00" in spend
    bal = redactor.redact_structured(_all_outputs()[1], RedactionMap()).text
    assert "45678.90" in bal and "XX1234" not in bal  # the masked account becomes a placeholder


def test_outputs_carry_no_reference_raw_sms_or_full_timestamp() -> None:
    for out in _all_outputs():
        text = json.dumps(out)
        assert REFERENCE not in text and RAW_SMS not in text and "debited" not in text
        assert not re.search(r"\d{2}:\d{2}:\d{2}", text)
        assert not re.search(r"\d{4}-\d{2}-\d{2}T", text)
