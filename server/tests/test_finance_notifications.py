"""Payment-app notifications through the SMS pipeline: parsing, source flag and dedup."""

from __future__ import annotations

from datetime import timedelta

from agent.finance.categorize import categorize_by_rules
from agent.finance.ingest import FinanceIngest, SmsIn
from agent.finance.ledger import NOTIFICATION_DEDUP_WINDOW, Ledger
from agent.finance.notif_parsers import parse_message
from agent.finance.sms_parsers import bank_for_sender
from agent.finance.store import FinanceStore, Source, StoredTxn
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from tests.finance_support import KEY, at, make_fin, txn
from tests.support import FakeClock

PHONEPE = "Money transfer successful\n₹150 has been sent to Test Person"
BOB_SMS = (
    "Rs.150.00 Dr. from A/C XXXXXX1234 and Cr. to shop@okaxis. Ref:400011112222. "
    "AvlBal:Rs.850.00(2026:10:05)"
)


def _real() -> tuple[FinanceIngest, FinanceStore]:
    db = Database(":memory:")
    clock = FakeClock()
    store = FinanceStore(db, FieldCipher(KEY), KEY, clock)
    ledger = Ledger(store, categorize_by_rules, clock)
    ingest = FinanceIngest(store, ledger, parse_message, bank_for_sender, lambda *_: None)
    return ingest, store


def _rows(store: FinanceStore) -> list[StoredTxn]:
    return store.txns_between(at(-600), at(600))


def test_phonepe_notification_becomes_a_notification_only_row() -> None:
    ingest, store = _real()
    result = ingest.ingest_sms_batch([SmsIn("APP-PHONEPE", PHONEPE, at())])
    assert (result.accepted, result.parsed) == (1, 1)
    [row] = _rows(store)
    assert (row.from_notification, row.from_sms, row.from_email) == (True, False, False)
    assert (row.bank, row.account_mask, row.direction, row.amount_paise) == (
        "upi",
        None,
        "debit",
        15000,
    )
    assert (row.counterparty, row.channel, row.inferred) == ("Test Person", "upi", False)


def test_notification_then_matching_bob_sms_is_one_row_with_both_flags() -> None:
    ingest, store = _real()
    ingest.ingest_sms_batch([SmsIn("APP-PHONEPE", PHONEPE, at())])
    ingest.ingest_sms_batch([SmsIn("AD-BOBTXN", BOB_SMS, at(2))])
    [row] = _rows(store)
    assert (row.from_notification, row.from_sms) == (True, True)
    assert row.account_mask == "XX1234" and row.balance_paise == 85000
    assert row.counterparty == "shop@okaxis"  # the bank's wording replaces the app's name


def test_bob_sms_then_matching_notification_keeps_the_sms_counterparty() -> None:
    ingest, store = _real()
    ingest.ingest_sms_batch([SmsIn("AD-BOBTXN", BOB_SMS, at())])
    ingest.ingest_sms_batch([SmsIn("APP-PHONEPE", PHONEPE, at(3))])
    [row] = _rows(store)
    assert (row.from_notification, row.from_sms) == (True, True)
    assert row.counterparty == "shop@okaxis" and row.account_mask == "XX1234"


def test_notification_fills_a_missing_counterparty_on_the_sms_row() -> None:
    env = make_fin()
    env.ledger.record(txn(counterparty=None, reference=None), at(), "sms")
    env.ledger.record(txn(bank="upi", account_mask=None, reference=None), at(1), "notification")
    [row] = env.store.txns_between(at(-5), at(5))
    assert row.counterparty == "Test Merchant" and row.from_notification and row.from_sms


def test_window_is_fifteen_minutes_either_order() -> None:
    assert timedelta(minutes=15) == NOTIFICATION_DEDUP_WINDOW
    cases: list[tuple[Source, Source, int, int]] = [
        ("sms", "notification", 15, 1),
        ("sms", "notification", 16, 2),
        ("notification", "sms", 15, 1),
        ("notification", "sms", 16, 2),
        ("email", "notification", 15, 1),
        ("notification", "email", 16, 2),
    ]
    for first, second, gap, rows in cases:
        env = make_fin()
        env.ledger.record(txn(reference=None), at(), first)
        env.ledger.record(txn(reference=None), at(gap), second)
        assert len(env.store.txns_between(at(-5), at(60))) == rows, (first, second, gap)


def test_sms_and_email_keep_their_two_hour_window() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None), at(), "sms")
    env.ledger.record(txn(reference=None), at(100), "email")
    [row] = env.store.txns_between(at(-5), at(200))
    assert (row.from_sms, row.from_email) == (True, True)
    # A notification 150 minutes after the merged row is far outside its 15 minutes.
    env.ledger.record(txn(reference=None), at(150), "notification")
    assert len(env.store.txns_between(at(-5), at(200))) == 2


def test_a_notification_is_never_matched_to_a_different_amount_or_direction() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None), at(), "sms")
    env.ledger.record(txn(reference=None, amount_paise=1), at(1), "notification")
    env.ledger.record(txn(reference=None, direction="credit"), at(1), "notification")
    assert len(env.store.txns_between(at(-5), at(5))) == 3


def test_two_notifications_are_never_merged() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None), at(), "notification")
    env.ledger.record(txn(reference=None), at(1), "notification")
    assert len(env.store.txns_between(at(-5), at(5))) == 2


def test_a_known_other_account_does_not_match() -> None:
    env = make_fin()
    env.ledger.record(txn(reference=None, account_mask="XX1234"), at(), "sms")
    env.ledger.record(txn(reference=None, account_mask="XX9999"), at(1), "notification")
    assert len(env.store.txns_between(at(-5), at(5))) == 2


def test_inferred_rows_are_never_dedup_candidates() -> None:
    for source in ("sms", "email", "notification"):
        env = make_fin()
        env.ledger.record(txn(reference=None, balance_paise=100000, amount_paise=100), at(), "sms")
        env.ledger.record(txn(reference=None, balance_paise=60000, amount_paise=100), at(60), "sms")
        env.reconciler.run()
        [inferred] = [t for t in env.store.txns_between(at(-5), at(120)) if t.inferred]
        assert inferred.amount_paise == 39900
        recorded, merged = env.ledger.record(
            txn(reference=None, amount_paise=39900, account_mask=None),
            inferred.occurred_at,
            source,  # type: ignore[arg-type]
        )
        assert recorded != inferred.id and not merged
        kept = env.store.get_txn(inferred.id)
        assert kept is not None
        assert not (kept.from_sms or kept.from_email or kept.from_notification)


def test_unparsed_notification_is_kept_encrypted_for_a_reparse() -> None:
    env = make_fin()
    body = "Some title\nSomething Test Person about ₹5"
    result = env.ingest.ingest_sms_batch([SmsIn("APP-PHONEPE", body, at())])
    # Kept like an unreadable SMS, but never counted as a bank-SMS parser failure.
    assert (result.unparsed, result.ignored, result.accepted) == (0, 1, 1)
    row = env.db.query("SELECT * FROM finance_sms")[0]
    assert row["status"] == "unparsed" and b"Test Person" not in bytes(row["body_enc"])
    again = env.ingest.ingest_sms_batch([SmsIn("APP-PHONEPE", body, at())])
    assert again.duplicates == 1

    # A later parser version reads it: the resend upgrades the stored row.
    env.parsers.sms[body] = txn(bank="upi", account_mask=None, reference=None)
    upgraded = env.ingest.ingest_sms_batch([SmsIn("APP-PHONEPE", body, at())])
    assert (upgraded.parsed, upgraded.duplicates) == (1, 0)
    assert env.db.query("SELECT status FROM finance_sms")[0]["status"] == "parsed"
    [stored] = env.store.txns_between(at(-5), at(5))
    assert stored.from_notification and not stored.from_sms


def test_secret_like_notification_is_never_stored() -> None:
    env = make_fin()
    env.ingest.ingest_sms_batch([SmsIn("APP-GPAY", "Security\nYour OTP is 123456", at())])
    row = env.db.query("SELECT * FROM finance_sms")[0]
    assert row["status"] == "ignored" and row["body_enc"] is None


def test_other_app_senders_are_ignored_and_keep_no_body() -> None:
    ingest, store = _real()
    result = ingest.ingest_sms_batch([SmsIn("APP-RANDOM", PHONEPE, at())])
    assert (result.ignored, result.parsed) == (1, 0)
    assert _rows(store) == []
    assert store.sms_status(store.sms_key("APP-RANDOM", PHONEPE, at())) == "ignored"
    # The sender constants are exact: a lower-case sender is not a payment app.
    assert ingest.ingest_sms_batch([SmsIn("app-phonepe", PHONEPE, at(1))]).ignored == 1
    assert _rows(store) == []


def test_bobworld_notification_is_a_notification_row_with_the_bank_account() -> None:
    ingest, store = _real()
    ingest.ingest_sms_batch([SmsIn("APP-BOBWORLD", f"BOB World\n{BOB_SMS}", at())])
    [row] = _rows(store)
    assert (row.bank, row.account_mask, row.from_notification, row.from_sms) == (
        "bob",
        "XX1234",
        True,
        False,
    )
    assert store.list_balances()[0].balance_paise == 85000
    assert store.list_balances()[0].source == "sms"
