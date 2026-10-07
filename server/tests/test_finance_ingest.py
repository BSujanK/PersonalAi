from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from agent.finance.ingest import SmsIn
from tests.finance_support import SENDER, at, balance, mail, make_fin, txn
from tests.support import START

BODY_A = "Test body A"
BODY_B = "Test body B"


def test_batch_parses_and_is_idempotent() -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = txn()
    env.parsers.sms[BODY_B] = balance()
    batch = [SmsIn(SENDER, BODY_A, at()), SmsIn(SENDER, BODY_B, at(1))]
    first = env.ingest.ingest_sms_batch(batch)
    assert (first.accepted, first.duplicates, first.parsed, first.balances) == (2, 0, 1, 1)
    second = env.ingest.ingest_sms_batch(batch)
    assert (second.accepted, second.duplicates, second.parsed) == (0, 2, 0)
    assert len(env.store.txns_between(at(-5), at(5))) == 1
    assert len(env.store.list_balances()) == 1


def test_duplicate_inside_one_batch_counts_once() -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = txn()
    result = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at())] * 2)
    assert (result.accepted, result.duplicates) == (1, 1)


def test_same_body_at_another_time_is_a_new_payment() -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = txn(reference=None)
    env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at()), SmsIn(SENDER, BODY_A, at(1))])
    assert len(env.store.txns_between(at(-5), at(5))) == 2


def test_ignored_sms_stores_no_body() -> None:
    env = make_fin()
    result = env.ingest.ingest_sms_batch(
        [
            SmsIn("AD-PROMO", "Big sale at example shop", at()),
            SmsIn(SENDER, "Your OTP is 123456. Do not share.", at(1)),
        ]
    )
    assert (result.ignored, result.unparsed) == (2, 0)
    rows = env.db.query("SELECT status, sender, body_enc FROM finance_sms ORDER BY received_at")
    assert {r["status"] for r in rows} == {"ignored"}
    assert all(r["body_enc"] is None for r in rows)
    assert [r["sender"] for r in rows] == ["", SENDER]  # a non-bank sender is not kept


def test_unparsed_bank_sms_keeps_encrypted_body() -> None:
    env = make_fin()
    body = "Unusual layout for Test Merchant 4242.00 somewhere"
    result = env.ingest.ingest_sms_batch([SmsIn(SENDER, body, at())])
    assert result.unparsed == 1
    row = env.db.query("SELECT * FROM finance_sms")[0]
    assert row["status"] == "unparsed" and b"Test Merchant" not in bytes(row["body_enc"])
    assert body not in str(dict(row))


def test_parser_crash_is_unparsed_not_a_failed_batch(caplog: pytest.LogCaptureFixture) -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = ValueError("secret text 4242")
    with caplog.at_level(logging.WARNING):
        result = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at())])
    assert result.unparsed == 1
    assert "secret" not in caplog.text and "ValueError" in caplog.text


def test_batch_is_atomic() -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = txn()
    env.parsers.sms[BODY_B] = RuntimeError("boom")
    original = env.store.insert_sms
    calls = 0

    def flaky(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("disk")
        original(*args, **kwargs)  # type: ignore[arg-type]

    env.store.insert_sms = flaky  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at()), SmsIn(SENDER, BODY_B, at(1))])
    assert env.db.query("SELECT 1 FROM finance_sms") == []
    assert env.db.query("SELECT 1 FROM finance_txns") == []


def test_email_ingest_records_once_and_merges_with_sms() -> None:
    env = make_fin()
    env.parsers.emails["Alert"] = txn()
    env.parsers.sms[BODY_A] = txn()
    env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at(-20))])
    env.ingest.ingest_email(mail("m1"))
    env.ingest.ingest_email(mail("m1"))
    [row] = env.store.txns_between(at(-60), at(60))
    assert (row.from_sms, row.from_email) == (True, True)
    assert env.db.query("SELECT status FROM finance_email_alerts")[0]["status"] == "parsed"


def test_email_skips_spam_trash_and_unknown_and_never_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = make_fin()
    env.parsers.emails["Alert"] = txn()
    env.ingest.ingest_email(mail("m1", label_ids=("SPAM",)))
    env.ingest.ingest_email(mail("m2", label_ids=("TRASH", "INBOX")))
    env.ingest.ingest_email(mail("m3", subject="Newsletter"))
    assert env.store.txns_between(at(-60), at(60)) == []
    assert [
        r["message_id"] for r in env.db.query("SELECT message_id FROM finance_email_alerts")
    ] == ["m3"]

    def boom(*_: object) -> None:
        raise RuntimeError("private text")

    env.ingest._parse_alert_email = boom  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING):
        env.ingest.ingest_email(mail("m4"))
    assert "private text" not in caplog.text and "RuntimeError" in caplog.text


def test_email_time_comes_from_internal_date() -> None:
    env = make_fin()
    env.parsers.emails["Alert"] = txn()
    env.ingest.ingest_email(
        mail("m1", internal_date=int((START + timedelta(hours=3)).timestamp() * 1000))
    )
    [row] = env.store.txns_between(at(170), at(190))
    assert row.occurred_at == at(180)


def test_resent_balance_only_sms_is_upgraded_after_a_parser_fix() -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = balance()  # an older parser only saw the balance
    first = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at())])
    assert first.balances == 1
    env.parsers.sms[BODY_A] = txn()  # the fixed parser reads the payment
    again = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at())])
    assert (again.accepted, again.duplicates, again.parsed) == (1, 0, 1)
    assert len(env.store.txns_between(at(-5), at(5))) == 1
    rows = env.db.query("SELECT status FROM finance_sms")
    assert [r["status"] for r in rows] == ["parsed"]
    third = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at())])
    assert (third.accepted, third.duplicates) == (0, 1)


def test_resent_unparsed_sms_stays_a_duplicate_while_still_unparsed() -> None:
    env = make_fin()
    body = "Unusual layout for Test Merchant 4242.00 somewhere"
    env.ingest.ingest_sms_batch([SmsIn(SENDER, body, at())])
    again = env.ingest.ingest_sms_batch([SmsIn(SENDER, body, at())])
    assert (again.accepted, again.duplicates) == (0, 1)


def test_same_sms_uploaded_twice_with_different_precision_counts_once() -> None:
    # The inbox scan reports whole seconds, the live receiver adds milliseconds.
    env = make_fin()
    env.parsers.sms[BODY_A] = txn()
    received = at()
    first = env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, received.replace(microsecond=0))])
    again = env.ingest.ingest_sms_batch(
        [SmsIn(SENDER, BODY_A, received.replace(microsecond=453000))]
    )
    assert (first.parsed, again.duplicates) == (1, 1)
    assert len(env.store.txns_between(at(-5), at(5))) == 1


def test_two_alerts_for_one_bank_reference_are_one_payment() -> None:
    # The bank sent two different SMS (two senders, an hour apart) for one payment.
    env = make_fin()
    env.parsers.sms[BODY_A] = txn(reference="400099990001")
    env.parsers.sms[BODY_B] = txn(reference="400099990001")
    env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at()), SmsIn("JK-BOBTXN-S", BODY_B, at(60))])
    assert len(env.store.txns_between(at(-5), at(120))) == 1


def test_different_references_stay_separate_payments() -> None:
    env = make_fin()
    env.parsers.sms[BODY_A] = txn(reference="400099990001")
    env.parsers.sms[BODY_B] = txn(reference="400099990002")
    env.ingest.ingest_sms_batch([SmsIn(SENDER, BODY_A, at()), SmsIn(SENDER, BODY_B, at(1))])
    assert len(env.store.txns_between(at(-5), at(5))) == 2
