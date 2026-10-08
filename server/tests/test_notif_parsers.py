from __future__ import annotations

import pytest

from agent.finance.model import APP_BOBWORLD, APP_GPAY, APP_PHONEPE, ParsedTxn
from agent.finance.notif_parsers import parse_message, parse_notification
from agent.finance.sms_parsers import bank_for_sender


def _fields(parsed: ParsedTxn | None) -> tuple[object, ...]:
    assert parsed is not None
    return (parsed.direction, parsed.amount_paise, parsed.counterparty, parsed.channel, parsed.bank)


def test_phonepe_money_sent_to_a_vpa() -> None:
    parsed = parse_notification(
        APP_PHONEPE, "Money transfer successful\n₹1 has been sent to someone123@okaxis"
    )
    assert _fields(parsed) == ("debit", 100, "someone123@okaxis", "upi", "upi")
    assert parsed is not None
    assert (parsed.account_mask, parsed.reference, parsed.balance_paise, parsed.txn_date) == (
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("text", "paise", "name"),
    [
        ("₹1,234.50 has been sent to Test Person", 123450, "Test Person"),
        ("₹12,00,000 has been sent to shop.test@okicici", 120000000, "shop.test@okicici"),
        ("₹99.5 has been sent to Test Person.", 9950, "Test Person"),
    ],
)
def test_phonepe_sent_amounts_and_names(text: str, paise: int, name: str) -> None:
    parsed = parse_notification(APP_PHONEPE, f"Money transfer successful\n{text}")
    assert _fields(parsed) == ("debit", paise, name, "upi", "upi")


@pytest.mark.parametrize(
    "body",
    [
        "Payment received\nReceived ₹250 from Test Person",
        "Payment received\n₹250 received from Test Person",
    ],
)
def test_phonepe_received(body: str) -> None:
    assert _fields(parse_notification(APP_PHONEPE, body)) == (
        "credit",
        25000,
        "Test Person",
        "upi",
        "upi",
    )


def test_gpay_paid_you() -> None:
    parsed = parse_notification(APP_GPAY, "Google Pay\nTest Person paid you ₹1,000.25")
    assert _fields(parsed) == ("credit", 100025, "Test Person", "upi", "upi")


@pytest.mark.parametrize(
    "body",
    [
        "Money transfer failed\n₹1 has been sent to someone123@okaxis",
        "Payment pending\n₹1 has been sent to someone123@okaxis",
        "Money transfer declined\n₹1 has been sent to someone123@okaxis",
        "Money transfer successful\n₹1 reversed: has been sent to someone123@okaxis",
        "Cashback\nReceived ₹5 from Test Person",
        "Reward unlocked\nReceived ₹5 from Test Person",
        "Offer\n₹5 received from Test Person",
        "Test Person requested\nReceived ₹5 from Test Person",
        "Payment due\n₹5 has been sent to a@okaxis",
        "Bill paid\n₹5 has been sent to a@okaxis",
        "Reminder\n₹5 has been sent to a@okaxis",
        "Scratch card\n₹5 has been sent to a@okaxis",
        "Coupon\n₹5 has been sent to a@okaxis",
        "Money transfer successful\n₹5 has been sent to Cashback Shop",
    ],
)
def test_phonepe_rejects_unsettled_or_promotional(body: str) -> None:
    assert parse_notification(APP_PHONEPE, body) is None


@pytest.mark.parametrize(
    "body",
    [
        "Google Pay\nTest Person paid you ₹5 as a reward",
        "Google Pay\nTest Person requested ₹5",
        "Google Pay\nTest Person paid you",
        "Google Pay\nTest Person paid you some money",
        "Google Pay failed\nTest Person paid you ₹5",
    ],
)
def test_gpay_rejects_everything_else(body: str) -> None:
    assert parse_notification(APP_GPAY, body) is None


@pytest.mark.parametrize(
    "body",
    [
        "",
        "Money transfer successful",
        "Money transfer successful\nhas been sent to someone123@okaxis",
        "Money transfer successful\n₹0 has been sent to someone123@okaxis",
        "Money transfer successful\nSomething else entirely",
        "Hello\nWelcome to PhonePe",
        "Money transfer successful\n₹1 has been sent to someone123@okaxis and more words ₹2",
    ],
)
def test_no_amount_or_unknown_template_is_none(body: str) -> None:
    assert parse_notification(APP_PHONEPE, body) is None


def test_gpay_does_not_read_phonepe_templates_and_back() -> None:
    sent = "Money transfer successful\n₹1 has been sent to someone123@okaxis"
    assert parse_notification(APP_GPAY, sent) is None
    assert parse_notification(APP_PHONEPE, "x\nTest Person paid you ₹5") is None


@pytest.mark.parametrize("sender", ["APP-OTHER", "app-phonepe", "AD-BOBTXN", "APP-PHONEPE ", ""])
def test_other_senders_are_none(sender: str) -> None:
    body = "Money transfer successful\n₹1 has been sent to someone123@okaxis"
    assert parse_notification(sender, body) is None


def test_bobworld_uses_the_bob_sms_parser_on_the_text() -> None:
    text = (
        "Rs.149.00 Dr. from A/C XXXXXX1234 and Cr. to shop@okaxis. Ref:400011112222. "
        "AvlBal:Rs.851.00(2026:10:05)"
    )
    parsed = parse_notification(APP_BOBWORLD, f"BOB World\n{text}")
    assert isinstance(parsed, ParsedTxn)
    assert (parsed.bank, parsed.account_mask, parsed.direction, parsed.amount_paise) == (
        "bob",
        "XX1234",
        "debit",
        14900,
    )
    assert (parsed.reference, parsed.balance_paise, parsed.counterparty) == (
        "400011112222",
        85100,
        "shop@okaxis",
    )


@pytest.mark.parametrize(
    "body",
    ["BOB World\nWelcome back", "BOB World\nYour OTP is 123456", "BOB World", ""],
)
def test_bobworld_unreadable_text_is_none(body: str) -> None:
    assert parse_notification(APP_BOBWORLD, body) is None


def test_bobworld_balance_only_text_is_not_a_transaction() -> None:
    body = "BOB World\nAvl Bal in A/c XX1234 is Rs.500.00"
    assert parse_notification(APP_BOBWORLD, body) is None


def test_reserved_senders_route_to_a_bank() -> None:
    assert bank_for_sender(APP_PHONEPE) == "upi"
    assert bank_for_sender(APP_GPAY) == "upi"
    assert bank_for_sender(APP_BOBWORLD) == "bob"
    for other in ("APP-FOO", "APP-BOBX", "app-phonepe", "APP-PHONEPE-S"):
        assert bank_for_sender(other) is None


def test_parse_message_dispatches_by_sender() -> None:
    notification = "Money transfer successful\n₹1 has been sent to someone123@okaxis"
    assert isinstance(parse_message(APP_PHONEPE, notification), ParsedTxn)
    sms = "Rs.250.00 debited from A/c XX1234 on 05-10-26 to VPA shop@okicici (UPI Ref No 4000)"
    parsed = parse_message("AD-BOBTXN", sms)
    assert isinstance(parsed, ParsedTxn) and parsed.amount_paise == 25000
    assert parse_message("AD-BOBTXN", notification) is not None  # an SMS reads as an SMS
