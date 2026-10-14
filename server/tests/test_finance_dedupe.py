"""The same bank SMS or payment must never be counted twice. Synthetic data only."""

from __future__ import annotations

from datetime import timedelta

from agent.finance.ingest import SmsIn
from tests.finance_support import SENDER, FinEnv, at, make_fin, txn

BODY = "Test body A"
NO_BALANCE = txn(reference=None)


def _bob_for_any_sender(env: FinEnv) -> None:
    env.ingest._bank_for_sender = lambda _sender: "bob"


def _counts(env: FinEnv) -> tuple[int, int]:
    sms = len(env.db.query("SELECT 1 FROM finance_sms"))
    return sms, len(env.store.txns_between(at(-60), at(60)))


def test_inbox_scan_and_live_receiver_stamps_of_one_sms_count_once() -> None:
    env = make_fin()
    env.parsers.sms[BODY] = NO_BALANCE
    inbox = at().replace(second=11, microsecond=0)
    receiver = inbox + timedelta(seconds=1, milliseconds=748)  # across a second boundary
    assert env.store.sms_key(SENDER, BODY, inbox) != env.store.sms_key(SENDER, BODY, receiver)

    first = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY, receiver)])
    second = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY, inbox)])

    assert (first.accepted, first.duplicates, first.parsed) == (1, 0, 1)
    assert (second.accepted, second.duplicates, second.parsed) == (0, 1, 0)
    assert _counts(env) == (1, 1)


def test_twin_inside_one_batch_counts_once() -> None:
    env = make_fin()
    env.parsers.sms[BODY] = NO_BALANCE
    inbox = at().replace(second=11, microsecond=0)
    result = env.ingest.ingest_sms_batch(
        [SmsIn(SENDER, BODY, inbox), SmsIn(SENDER, BODY, inbox + timedelta(milliseconds=1748))]
    )
    assert (result.accepted, result.duplicates) == (1, 1)
    assert _counts(env) == (1, 1)


def test_operator_prefix_does_not_make_a_different_message() -> None:
    env = make_fin()
    _bob_for_any_sender(env)
    env.parsers.sms[BODY] = NO_BALANCE
    env.ingest.ingest_sms_batch([SmsIn("JK-BOBTXN-S", BODY, at())])
    result = env.ingest.ingest_sms_batch([SmsIn("JX-BOBTXN-S", BODY, at().replace(second=30))])
    assert (result.accepted, result.duplicates) == (0, 1)
    assert _counts(env) == (1, 1)


def test_another_sender_with_the_same_text_is_another_message() -> None:
    env = make_fin()
    _bob_for_any_sender(env)
    env.parsers.sms[BODY] = NO_BALANCE
    result = env.ingest.ingest_sms_batch(
        [SmsIn("JK-BOBTXN-S", BODY, at()), SmsIn("JK-OTHERB-S", BODY, at())]
    )
    assert (result.accepted, result.duplicates) == (2, 0)


def test_the_same_text_ten_minutes_later_is_a_genuine_repeat() -> None:
    env = make_fin()
    env.parsers.sms[BODY] = NO_BALANCE
    result = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY, at()), SmsIn(SENDER, BODY, at(10))])
    assert (result.accepted, result.duplicates) == (2, 0)
    assert _counts(env) == (2, 2)


def test_body_hash_is_stored_and_the_text_is_not() -> None:
    env = make_fin()
    env.parsers.sms[BODY] = NO_BALANCE
    env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY, at())])
    row = env.db.query("SELECT body_hash FROM finance_sms")[0]
    assert row["body_hash"] == env.store.body_hash(SENDER, BODY)
    assert BODY not in row["body_hash"]


def test_twin_of_an_unparsed_message_is_also_a_duplicate() -> None:
    env = make_fin()
    body = "Unusual layout for Test Merchant 4242.00 somewhere"
    env.ingest.ingest_sms_batch([SmsIn(SENDER, body, at())])
    result = env.ingest.ingest_sms_batch([SmsIn(SENDER, body, at() + timedelta(seconds=2))])
    assert (result.accepted, result.duplicates) == (0, 1)


# --- payment level ---------------------------------------------------------------------------


def test_different_balances_one_minute_apart_are_two_payments() -> None:
    env = make_fin()
    first, _ = env.ledger.record(txn(reference=None, balance_paise=500000), at(), "sms")
    second, merged = env.ledger.record(txn(reference=None, balance_paise=376550), at(1), "sms")
    assert (first != second, merged) == (True, False)
    assert len(env.store.txns_between(at(-5), at(5))) == 2


def test_same_amount_and_balance_seconds_apart_is_one_payment_even_from_one_source() -> None:
    env = make_fin()
    first, _ = env.ledger.record(txn(reference=None, balance_paise=500000), at(), "sms")
    second, merged = env.ledger.record(
        txn(reference=None, balance_paise=500000), at() + timedelta(seconds=30), "sms"
    )
    assert (second, merged) == (first, True)
    assert len(env.store.txns_between(at(-5), at(5))) == 1


def test_same_amount_and_balance_across_sources_is_one_payment() -> None:
    env = make_fin()
    first, _ = env.ledger.record(txn(reference=None, balance_paise=500000), at(), "sms")
    second, merged = env.ledger.record(txn(reference="REF1", balance_paise=500000), at(8), "email")
    assert (second, merged) == (first, True)
    [row] = env.store.txns_between(at(-5), at(15))
    assert (row.from_sms, row.from_email) == (True, True)


def test_same_amount_and_balance_twenty_minutes_apart_are_two_payments() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None, balance_paise=500000), at(), "sms")
    _, merged = env.ledger.record(txn(reference=None, balance_paise=500000), at(20), "sms")
    assert merged is False
    assert len(env.store.txns_between(at(-5), at(25))) == 2


def test_a_row_without_a_balance_never_matches_by_balance() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None), at(), "sms")
    _, merged = env.ledger.record(txn(reference=None, balance_paise=500000), at(1), "sms")
    assert merged is False
    _, merged = env.ledger.record(txn(reference=None), at(2), "sms")  # no balance: no match either
    assert merged is False


def test_another_account_or_direction_never_matches_by_balance() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None, balance_paise=500000), at(), "sms")
    _, other_account = env.ledger.record(
        txn(reference=None, account_mask="XX9999", balance_paise=500000), at(1), "sms"
    )
    _, other_direction = env.ledger.record(
        txn(reference=None, direction="credit", balance_paise=500000), at(1), "sms"
    )
    assert (other_account, other_direction) == (False, False)


def test_inferred_rows_never_match_by_balance() -> None:
    env = make_fin()
    env.store.insert_inferred(
        txn(reference=None, balance_paise=500000), at(), (at(-5), at(5)), ("other", "rule")
    )
    _, merged = env.ledger.record(txn(reference=None, balance_paise=500000), at(1), "sms")
    assert merged is False
