"""Unrecorded (inferred) rows in the LLM-facing tools, the categoriser, config and startup."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from agent.config import Settings
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.finance.categorize import (
    CATEGORIES,
    SYSTEM_PROMPT,
    FinanceCategorizer,
    categorize_by_rules,
)
from agent.finance.ledger import Ledger
from agent.finance.services import setup_finance
from agent.finance.store import FinanceStore
from agent.finance.summary import spend_summary
from agent.finance.tools import register_finance_tools
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from tests.finance_support import KEY, at, make_fin, txn
from tests.support import START, FakeClock
from tests.test_finance_categorize import ScriptedLLM

NOW = datetime(2026, 10, 5, 6, 30, tzinfo=UTC)  # 12:00 IST


def _with_gap() -> tuple[ToolRegistry, Any]:
    env = make_fin()
    env.clock.now = NOW
    registry = ToolRegistry()
    register_finance_tools(registry, env.store, env.clock, 330)
    env.ledger.record(
        txn(reference=None, balance_paise=90000, amount_paise=10000),
        datetime(2026, 10, 5, 1, 0, tzinfo=UTC),
        "sms",
    )
    env.ledger.record(
        txn(reference=None, balance_paise=70000, amount_paise=5000),
        datetime(2026, 10, 5, 3, 0, tzinfo=UTC),
        "sms",
    )
    env.reconciler.run()
    return registry, env


def _run(registry: ToolRegistry, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = registry.get(name)
    assert tool is not None
    result = tool.run(args)
    assert isinstance(result, dict)
    return result


def test_spend_summary_tool_includes_and_discloses_unrecorded_money() -> None:
    registry, _ = _with_gap()
    out = _run(registry, "spend_summary", {"period": "today"})
    assert (out["spent_inr"], out["unrecorded_inr"]) == ("300.00", "150.00")
    assert {"category": "unrecorded", "total_inr": "150.00", "count": 1} in out["by_category"]
    assert all(p["name"] for p in out["top_counterparties"])  # the inferred row has no name
    only = _run(registry, "spend_summary", {"period": "today", "category": "unrecorded"})
    assert (only["count"], only["spent_inr"]) == (1, "150.00")


def test_transactions_tool_reports_unrecorded_and_never_returns_rows() -> None:
    registry, _ = _with_gap()
    out = _run(registry, "transactions", {"period": "today", "group_by": "account"})
    assert (out["total_inr"], out["unrecorded_inr"]) == ("300.00", "150.00")
    credit = _run(registry, "transactions", {"period": "today", "direction": "credit"})
    assert credit["unrecorded_inr"] == "0.00"
    dumped = json.dumps(out)
    assert "occurred_at" not in dumped and "window" not in dumped and "id" not in out


def test_unrecorded_credits_are_not_counted_as_unrecorded_spending() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None, balance_paise=90000, amount_paise=10000), at(), "sms")
    env.ledger.record(txn(reference=None, balance_paise=130000, amount_paise=5000), at(60), "sms")
    env.reconciler.run()
    summary = spend_summary(env.store.txns_between(at(-5), at(120)))
    assert summary["unrecorded_inr"] == "0.00" and summary["received_inr"] == "450.00"


def test_the_model_is_never_offered_or_trusted_with_the_unrecorded_category() -> None:
    assert "unrecorded" in CATEGORIES and "unrecorded" not in SYSTEM_PROMPT
    env = make_fin()
    llm = ScriptedLLM('{"category": "unrecorded"}')
    categorizer = FinanceCategorizer(env.store, llm, Redactor())
    row, _ = env.ledger.record(txn(counterparty="Unknown Shop", reference="9"), at(), "sms")
    assert categorizer.run() == 0
    stored = env.store.get_txn(row)
    assert stored is not None and stored.category is None


def test_inferred_rows_are_never_queued_for_categorisation() -> None:
    _, env = _with_gap()
    queued = env.store.uncategorized(10)
    assert queued and not any(t.inferred for t in queued)


def test_unrecorded_can_be_an_owner_rule_category() -> None:
    assert categorize_by_rules("Test Merchant", "debit", "upi", "unrecorded") == (
        "unrecorded",
        "user_rule",
    )


def test_reconcile_limit_setting() -> None:
    assert Settings().reconcile_max_inr == 5000
    assert Settings.from_env({"PERSONALAI_RECONCILE_MAX_INR": "250"}).reconcile_max_inr == 250
    for bad in ("0", "-1", "abc", ""):
        with pytest.raises(ValueError, match="PERSONALAI_RECONCILE_MAX_INR"):
            Settings.from_env({"PERSONALAI_RECONCILE_MAX_INR": bad})


def test_setup_reconciles_once_at_startup_with_the_configured_limit() -> None:
    db = Database(":memory:")
    clock = FakeClock(START)
    store = FinanceStore(db, FieldCipher(KEY), KEY, clock)
    ledger = Ledger(store, categorize_by_rules, clock)
    ledger.record(txn(reference=None, balance_paise=90000, amount_paise=10000), at(-200), "sms")
    ledger.record(txn(reference=None, balance_paise=70000, amount_paise=5000), at(-100), "sms")
    ledger.record(txn(reference=None, balance_paise=-9000000, amount_paise=100), at(-50), "sms")

    services = setup_finance(Settings(reconcile_max_inr=200), db, KEY, ToolRegistry(), clock)
    inferred = [t for t in store.txns_between(at(-300), at(0)) if t.inferred]
    assert [t.amount_paise for t in inferred] == [15000]
    [mismatch] = services.reconciler.mismatches
    assert mismatch.gap_paise == -9000000 - 70000 + 100
