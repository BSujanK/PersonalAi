"""Balance-gap reconciliation over synthetic ledgers (fake accounts, paise throughout)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agent.finance.ingest import SmsIn
from agent.finance.reconcile import reconcile
from agent.finance.store import Source, StoredTxn
from tests.finance_support import SENDER, FinEnv, at, make_fin, txn
from tests.support import START


def _record(
    env: FinEnv, minutes: float, direction: str, amount: int, balance: int | None, **kw: Any
) -> int:
    source: Source = kw.pop("source", "sms")
    parsed = txn(
        direction=direction, amount_paise=amount, balance_paise=balance, reference=None, **kw
    )
    return env.ledger.record(parsed, at(0) + timedelta(minutes=minutes), source)[0]


def _run(env: FinEnv, **kw: Any) -> Any:
    return reconcile(env.store, START + timedelta(hours=6), **kw)


def _inferred(env: FinEnv) -> list[StoredTxn]:
    return [t for t in env.store.txns_between(at(-1000), at(1000)) if t.inferred]


def test_consistent_balances_make_no_row() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 85000)
    _record(env, 120, "credit", 20000, 105000)
    result = _run(env)
    assert (result.inserted, result.updated, result.deleted, result.mismatches) == (0, 0, 0, ())
    assert _inferred(env) == []


def test_a_single_anchor_or_no_balance_makes_no_row() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, None)
    assert _run(env).inserted == 0


def test_a_missing_debit_becomes_an_unrecorded_row() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 70000)  # 90000 - 5000 would be 85000: 15000 went missing
    result = _run(env)
    assert (result.inserted, result.mismatches) == (1, ())
    [row] = _inferred(env)
    assert (row.direction, row.amount_paise, row.channel, row.counterparty) == (
        "debit",
        15000,
        "other",
        None,
    )
    assert (row.bank, row.account_mask, row.category, row.category_source) == (
        "bob",
        "XX1234",
        "unrecorded",
        "rule",
    )
    assert row.occurred_at == at(30)  # midpoint of the window
    assert (row.window_from, row.window_to) == (at(0), at(60))
    assert (row.from_sms, row.from_email, row.from_notification, row.inferred) == (
        False,
        False,
        False,
        True,
    )
    assert row.account_hash == env.store.account_hash("bob", "XX1234")


def test_a_missing_credit_becomes_an_unrecorded_credit() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 135000)  # 85000 expected: 50000 came in unseen
    _run(env)
    [row] = _inferred(env)
    assert (row.direction, row.amount_paise) == ("credit", 50000)


def test_inferred_amounts_and_account_are_encrypted_at_rest() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 70000)
    _run(env)
    [row] = _inferred(env)
    raw = env.db.query("SELECT * FROM finance_txns WHERE id = ?", (row.id,))[0]
    assert b"15000" not in bytes(raw["amount_enc"]) and b"XX1234" not in bytes(
        raw["account_mask_enc"]
    )


def test_two_messages_in_the_same_minute_out_of_order_make_no_false_gap() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    # Real order: 90000 -> 85000 -> 75000, stored the other way round at the same instant.
    _record(env, 60, "debit", 10000, 75000, counterparty="B")
    _record(env, 60, "debit", 5000, 85000, counterparty="A")
    result = _run(env)
    assert (result.inserted, result.mismatches) == (0, ())
    assert _inferred(env) == []


def test_real_total_bal_versus_avlbl_amt_pair_has_no_gap() -> None:
    # Anchors 90000.04, then a 17.40 debit (balance 89982.64) and a 50005 NEFT debit
    # (balance 39977.64), both stamped in the same second; the NEFT row was stored first.
    env = make_fin()
    _record(env, -30, "credit", 100, 9000004)
    _record(env, 0, "debit", 5000500, 3997764, counterparty="SOME NAME")
    _record(env, 0, "debit", 1740, 8998264, counterparty="OTHER NAME")
    result = _run(env)
    assert (result.inserted, result.mismatches) == (0, ())


def test_a_real_gap_inside_a_cluster_is_still_found() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 1, "debit", 1000, 79000)  # 89000 expected: 10000 missing
    _run(env)
    [row] = _inferred(env)
    assert (row.direction, row.amount_paise) == ("debit", 10000)


def test_a_later_notification_fills_the_gap_and_the_row_goes() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 75000)
    _run(env)
    assert [t.amount_paise for t in _inferred(env)] == [10000]
    _record(env, 30, "debit", 10000, None, source="notification", bank="upi", account_mask=None)
    result = _run(env)
    assert (result.deleted, result.inserted, result.mismatches) == (1, 0, ())
    assert _inferred(env) == []


def test_a_partial_fill_reduces_the_amount_and_keeps_the_row() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 75000)
    _run(env)
    [before] = _inferred(env)
    _record(env, 30, "debit", 4000, None, source="notification", bank="upi", account_mask=None)
    result = _run(env)
    assert (result.updated, result.inserted, result.deleted) == (1, 0, 0)
    [after] = _inferred(env)
    assert after.id == before.id and after.amount_paise == 6000


def test_a_gap_over_the_limit_is_a_mismatch_not_a_row() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 85000 - 600000)
    result = _run(env)
    assert _inferred(env) == [] and result.inserted == 0
    [mismatch] = result.mismatches
    assert (mismatch.account_mask, mismatch.bank, mismatch.gap_paise) == ("XX1234", "bob", -600000)
    assert (mismatch.window_from, mismatch.window_to) == (at(0), at(60))
    # The limit is inclusive and configurable.
    assert _run(env, max_gap_paise=600000).inserted == 1
    assert _run(env, max_gap_paise=599999).deleted == 1


def test_a_difference_under_one_rupee_is_ignored() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 85000 - 99)
    assert _run(env).inserted == 0
    _record(env, 120, "debit", 5000, 80000 - 100 - 99)
    assert _run(env).inserted == 1


def test_running_twice_changes_nothing() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 70000)
    _record(env, 120, "credit", 1000, 100000)
    first = _run(env)
    ids = [t.id for t in _inferred(env)]
    second = _run(env)
    assert first.inserted == 2 and (second.inserted, second.updated, second.deleted) == (0, 0, 0)
    assert [t.id for t in _inferred(env)] == ids
    assert second.mismatches == first.mismatches


def test_an_owner_category_on_an_inferred_row_survives_reruns() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 75000)
    _run(env)
    [row] = _inferred(env)
    assert env.store.set_category(row.id, "food", "user")
    _run(env)
    _record(env, 30, "debit", 4000, None, source="notification", bank="upi", account_mask=None)
    _run(env)
    [after] = _inferred(env)
    assert (after.id, after.category, after.category_source) == (row.id, "food", "user")
    assert after.amount_paise == 6000


def test_a_new_message_inside_a_window_replaces_the_old_row() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 120, "debit", 5000, 60000)  # 25000 missing across two hours
    _run(env)
    [first] = _inferred(env)
    _record(env, 60, "debit", 5000, 80000)  # splits the window: 5000 missing + 15000 missing
    result = _run(env)
    amounts = sorted(t.amount_paise for t in _inferred(env))
    assert amounts == [5000, 15000] and result.deleted == 1
    assert first.id not in {t.id for t in _inferred(env)}


def test_account_less_rows_count_only_with_a_single_balance_account() -> None:
    def build(second_account: bool) -> FinEnv:
        env = make_fin()
        _record(env, 0, "debit", 10000, 90000)
        _record(env, 30, "debit", 10000, None, source="notification", bank="upi", account_mask=None)
        _record(env, 60, "debit", 5000, 75000)
        if second_account:
            _record(env, 20, "debit", 100, 500000, account_mask="XX9999", bank="hdfc")
        return env

    single = build(False)
    assert _run(single).inserted == 0 and _inferred(single) == []
    double = build(True)
    _run(double)
    [row] = [t for t in _inferred(double) if t.account_mask == "XX1234"]
    assert (row.direction, row.amount_paise) == ("debit", 10000)


def test_another_accounts_rows_are_not_counted() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 30, "debit", 7000, None, account_mask="XX9999")
    _record(env, 60, "debit", 5000, 85000)
    assert _run(env).inserted == 0


def test_rows_older_than_the_lookback_are_left_alone() -> None:
    env = make_fin()
    _record(env, 0, "debit", 10000, 90000)
    _record(env, 60, "debit", 5000, 70000)
    assert reconcile(env.store, START + timedelta(days=200)).inserted == 0
    assert reconcile(env.store, START + timedelta(days=100)).inserted == 1
    # Outside the window the stored row is out of scope, not unjustified.
    assert reconcile(env.store, START + timedelta(days=200)).deleted == 0
    assert len(_inferred(env)) == 1


def test_ingest_runs_the_reconcile_and_remembers_mismatches() -> None:
    env = make_fin()
    env.parsers.sms["one"] = txn(balance_paise=90000, reference=None, amount_paise=10000)
    env.parsers.sms["two"] = txn(balance_paise=70000, reference=None, amount_paise=5000)
    env.parsers.sms["far"] = txn(balance_paise=-900000, reference=None, amount_paise=5000)
    env.ingest.ingest_sms_batch([SmsIn(SENDER, "one", at(-300))])
    assert _inferred(env) == []
    env.ingest.ingest_sms_batch([SmsIn(SENDER, "two", at(-200))])
    [row] = _inferred(env)
    assert row.amount_paise == 15000
    env.ingest.ingest_sms_batch([SmsIn(SENDER, "far", at(-100))])
    [mismatch] = env.reconciler.mismatches
    assert mismatch.gap_paise == -900000 - 70000 + 5000


def test_a_failing_reconcile_never_blocks_the_ingest() -> None:
    env = make_fin()

    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret detail")

    env.store.txns_since = boom  # type: ignore[method-assign]
    env.parsers.sms["one"] = txn(reference=None)
    result = env.ingest.ingest_sms_batch([SmsIn(SENDER, "one", at())])
    assert result.parsed == 1
    assert env.reconciler.mismatches == ()
