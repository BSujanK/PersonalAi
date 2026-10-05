from __future__ import annotations

from datetime import timedelta

from tests.finance_support import at, balance, make_fin, txn


def test_store_columns_are_encrypted_and_hashes_are_keyed() -> None:
    env = make_fin()
    txn_id, _ = env.ledger.record(txn(balance_paise=987654), at(), "sms")
    row = env.db.query("SELECT * FROM finance_txns WHERE id = ?", (txn_id,))[0]
    blob = b"".join(
        bytes(row[c]) for c in ("amount_enc", "account_mask_enc", "counterparty_enc", "balance_enc")
    )
    for plain in (b"123450", b"XX1234", b"Test Merchant", b"987654"):
        assert plain not in blob
    for column in ("account_hash", "counterparty_hash", "reference_hash"):
        assert "400011112222" not in str(row[column]) and len(row[column]) == 64
    stored = env.store.get_txn(txn_id)
    assert stored is not None
    assert (
        stored.amount_paise,
        stored.account_mask,
        stored.counterparty,
        stored.balance_paise,
    ) == (
        123450,
        "XX1234",
        "Test Merchant",
        987654,
    )
    bal = env.db.query("SELECT * FROM finance_balances")[0]
    assert b"987654" not in bytes(bal["balance_enc"]) and b"XX1234" not in bytes(
        bal["account_mask_enc"]
    )


def test_rule_categorisation_on_insert_and_owner_rule_wins() -> None:
    env = make_fin()
    first, _ = env.ledger.record(txn(counterparty="swiggy@okicici", reference="1"), at(), "sms")
    assert env.store.get_txn(first).category == "food"  # type: ignore[union-attr]
    env.store.set_category_rule("Test Merchant", "health")
    second, _ = env.ledger.record(txn(reference="2"), at(1), "sms")
    stored = env.store.get_txn(second)
    assert stored is not None and (stored.category, stored.category_source) == (
        "health",
        "user_rule",
    )
    third, _ = env.ledger.record(txn(counterparty="Unknown Shop", reference="3"), at(2), "sms")
    assert env.store.get_txn(third).category is None  # type: ignore[union-attr]


def test_sms_then_email_merge_and_fill_missing_fields() -> None:
    env = make_fin()
    sms_id, merged = env.ledger.record(
        txn(reference=None, counterparty=None, account_mask=None), at(), "sms"
    )
    assert not merged
    email_id, merged = env.ledger.record(txn(balance_paise=555500), at(30), "email")
    assert merged and email_id == sms_id
    row = env.store.get_txn(sms_id)
    assert row is not None
    assert (row.from_sms, row.from_email) == (True, True)
    assert (row.counterparty, row.account_mask, row.balance_paise) == (
        "Test Merchant",
        "XX1234",
        555500,
    )
    assert row.reference_hash is not None and row.account_hash is not None
    assert len(env.store.txns_between(at(-60), at(60))) == 1


def test_email_then_sms_merge() -> None:
    env = make_fin()
    email_id, _ = env.ledger.record(txn(), at(), "email")
    sms_id, merged = env.ledger.record(txn(reference=None), at(90), "sms")
    assert merged and sms_id == email_id


def test_identical_payments_from_one_source_are_not_merged() -> None:
    env = make_fin()
    first, _ = env.ledger.record(txn(reference=None), at(), "sms")
    second, merged = env.ledger.record(txn(reference=None), at(1), "sms")
    assert not merged and first != second
    # An email for the same payment folds into one of them only.
    third, merged = env.ledger.record(txn(reference=None), at(2), "email")
    assert merged and third == second
    assert len(env.store.txns_between(at(-5), at(10))) == 2


def test_no_merge_outside_window_or_for_other_amount_direction_account() -> None:
    env = make_fin()
    base, _ = env.ledger.record(txn(reference=None), at(), "sms")
    for other in (
        (txn(reference=None), at(121)),
        (txn(reference=None, amount_paise=1), at(5)),
        (txn(reference=None, direction="credit"), at(5)),
        (txn(reference=None, account_mask="XX9999"), at(5)),
    ):
        txn_id, merged = env.ledger.record(other[0], other[1], "email")
        assert not merged and txn_id != base


def test_reference_merge_ignores_amount_and_time_window() -> None:
    env = make_fin()
    sms_id, _ = env.ledger.record(txn(), at(), "sms")
    email_id, merged = env.ledger.record(
        txn(amount_paise=99, account_mask=None), at() + timedelta(hours=1, minutes=59), "email"
    )
    assert merged and email_id == sms_id


def test_merge_picks_closest_in_time() -> None:
    env = make_fin()
    far, _ = env.ledger.record(txn(reference=None), at(-100), "sms")
    near, _ = env.ledger.record(txn(reference=None), at(-10), "sms")
    merged_id, merged = env.ledger.record(txn(reference=None), at(), "email")
    assert merged and merged_id == near != far


def test_balance_only_moves_forward() -> None:
    env = make_fin()
    assert env.ledger.record_balance(balance(balance_paise=100), at(10), "sms")
    assert not env.ledger.record_balance(balance(balance_paise=200), at(5), "sms")
    assert not env.ledger.record_balance(balance(balance_paise=300), at(10), "email")
    assert env.ledger.record_balance(balance(balance_paise=400), at(20), "email")
    [stored] = env.store.list_balances()
    assert (stored.balance_paise, stored.account_mask, stored.source) == (400, "XX1234", "email")
    # A transaction carrying an older balance does not rewind it either.
    env.ledger.record(txn(balance_paise=1), at(1), "sms")
    assert env.store.list_balances()[0].balance_paise == 400
    env.ledger.record(txn(balance_paise=777, reference="9"), at(30), "sms")
    assert env.store.list_balances()[0].balance_paise == 777


def test_different_references_are_never_merged() -> None:
    env = make_fin()
    sms_id, _ = env.ledger.record(txn(reference="111111111111"), at(), "sms")
    email_id, merged = env.ledger.record(txn(reference="222222222222"), at(1), "email")
    assert not merged and email_id != sms_id
