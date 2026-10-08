from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from agent.core.llm import ChatMessage, LLMResponse, LLMUnavailable
from agent.core.redact import Redactor, from_model
from agent.finance.categorize import CATEGORIES, FinanceCategorizer, categorize_by_rules
from tests.finance_support import at, make_fin, txn


@pytest.mark.parametrize(
    ("counterparty", "direction", "channel", "owner", "expected"),
    [
        ("Swiggy Order", "debit", "upi", None, ("food", "rule")),
        ("zepto@okicici", "debit", "upi", None, ("groceries", "rule")),
        ("AMAZON PAY", "debit", "card", None, ("shopping", "rule")),
        ("IRCTC", "debit", "netbanking", None, ("travel", "rule")),
        ("HPCL Pump", "debit", "card", None, ("fuel", "rule")),
        ("Vi ", "debit", "upi", None, ("bills", "rule")),
        ("Netflix", "debit", "card", None, ("subscriptions", "rule")),
        ("City Hospital", "debit", "upi", None, ("health", "rule")),
        ("State University", "debit", "neft", None, ("education", "rule")),
        ("Zerodha", "debit", "upi", None, ("investment", "rule")),
        (None, "debit", "atm", None, ("cash", "rule")),
        ("ACME SALARY OCT", "credit", "neft", None, ("income", "rule")),
        ("SMS charges", "debit", "other", None, ("fees", "rule")),
        ("Swiggy", "debit", "upi", "health", ("health", "user_rule")),
        ("Test Merchant", "debit", "upi", None, None),
        (None, "debit", "upi", None, None),
    ],
)
def test_rules(
    counterparty: str | None,
    direction: str,
    channel: str,
    owner: str | None,
    expected: tuple[str, str] | None,
) -> None:
    assert categorize_by_rules(counterparty, direction, channel, owner) == expected


class ScriptedLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.seen: list[list[ChatMessage]] = []

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        self.seen.append(list(messages))
        if isinstance(self.reply, Exception):
            raise self.reply
        return LLMResponse(from_model(self.reply), [])


def _setup(reply: str | Exception | None) -> tuple[FinanceCategorizer, Any, ScriptedLLM | None]:
    env = make_fin()
    llm = ScriptedLLM(reply) if reply is not None else None
    return FinanceCategorizer(env.store, llm, Redactor()), env, llm


def test_llm_path_sends_only_wrapped_counterparty_direction_channel() -> None:
    cat, env, llm = _setup('Sure: {"category": "entertainment"}')
    txn_id, _ = env.ledger.record(
        txn(counterparty="Test Merchant", reference="400011112222", balance_paise=987654),
        at(),
        "sms",
    )
    assert cat.run() == 1
    row = env.store.get_txn(txn_id)
    assert (row.category, row.category_source) == ("entertainment", "llm")
    assert llm is not None
    sent = "\n".join(m.content.text for m in llm.seen[0])
    assert '<untrusted_data source="transaction">' in sent
    assert "Test Merchant" in sent and "debit" in sent and "upi" in sent
    for leaked in ("1234.50", "123450", "XX1234", "400011112222", "987654", "9876.54"):
        assert leaked not in sent


def test_vpa_counterparty_is_redacted_before_the_model() -> None:
    cat, env, llm = _setup('{"category": "other"}')
    env.ledger.record(txn(counterparty="someone@okicici"), at(), "sms")
    cat.run()
    assert llm is not None and "someone@okicici" not in llm.seen[0][1].content.text


@pytest.mark.parametrize("reply", ["not json", '{"category": "gold-plating"}', '{"category": 3}'])
def test_invalid_reply_leaves_row_uncategorised_for_retry(reply: str) -> None:
    cat, env, _ = _setup(reply)
    txn_id, _ = env.ledger.record(txn(), at(), "sms")
    assert cat.run() == 0
    assert env.store.get_txn(txn_id).category is None


def test_unavailable_model_leaves_rows_and_stops_early() -> None:
    cat, env, llm = _setup(LLMUnavailable("down"))
    ids = [env.ledger.record(txn(reference=str(i)), at(i), "sms")[0] for i in range(3)]
    assert cat.run() == 0
    assert all(env.store.get_txn(i).category is None for i in ids)
    assert llm is not None and len(llm.seen) == 1


def test_no_llm_still_applies_rules_and_owner_rules() -> None:
    cat, env, _ = _setup(None)
    first, _ = env.ledger.record(txn(), at(), "sms")
    env.store.set_category_rule("Test Merchant", "rent")
    no_party, _ = env.ledger.record(txn(counterparty=None, reference="2"), at(1), "sms")
    assert cat.run() == 2
    assert env.store.get_txn(first).category == "rent"
    assert env.store.get_txn(no_party).category == "other"


def test_categories_are_the_documented_list() -> None:
    assert len(CATEGORIES) == 18 and "other" in CATEGORIES and json.dumps(CATEGORIES)
    assert "unrecorded" in CATEGORIES
