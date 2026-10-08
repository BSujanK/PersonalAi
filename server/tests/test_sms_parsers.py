from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent.finance.model import ParsedBalance, ParsedTxn
from agent.finance.sms_parsers import bank_for_sender, parse_sms
from agent.finance.sms_parsers.common import (
    find_account_mask,
    find_balance,
    find_date,
    find_reference,
    normalize_sender,
    parse_amount,
)

FIXTURES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "bank_sms.json").read_text(encoding="utf-8")
)


def _actual(sender: str, body: str) -> dict[str, Any] | None:
    parsed = parse_sms(sender, body)
    if parsed is None:
        return None
    fields = asdict(parsed)
    if isinstance(parsed, ParsedTxn):
        fields["txn_date"] = parsed.txn_date.isoformat() if parsed.txn_date else None
        return {"kind": "txn", **fields}
    assert isinstance(parsed, ParsedBalance)
    return {"kind": "balance", **fields}


@pytest.mark.parametrize("case", FIXTURES, ids=[f"{i:03d}" for i in range(len(FIXTURES))])
def test_fixture_exact_match(case: dict[str, Any]) -> None:
    assert _actual(case["sender"], case["body"]) == case["expected"]


def test_fixture_coverage() -> None:
    by_bank: dict[str, int] = {}
    for case in FIXTURES:
        if case["expected"]:
            bank = case["expected"]["bank"]
            by_bank[bank] = by_bank.get(bank, 0) + 1
    assert by_bank["bob"] >= 25
    assert all(by_bank[bank] >= 6 for bank in ("hdfc", "sbi", "icici", "axis", "kotak", "canara"))
    assert by_bank["upi"] >= 6
    assert sum(1 for case in FIXTURES if case["expected"] is None) >= 10


def test_field_accuracy_at_least_95_percent() -> None:
    total = correct = 0
    for case in FIXTURES:
        expected, actual = case["expected"], _actual(case["sender"], case["body"])
        if expected is None:
            total += 1
            correct += actual is None
            continue
        for key, value in expected.items():
            total += 1
            correct += actual is not None and actual.get(key) == value
    assert correct / total >= 0.95, f"{correct}/{total}"


@pytest.mark.parametrize(
    "body",
    [
        "",
        " ",
        "Rs.",
        "A/c",
        "Avl Bal",
        "debited " * 500,
        "\x00\xff" * 50,
        "Rs.9" * 400,
        "@@@ ... ---",
    ],
)
def test_garbage_never_raises(body: str) -> None:
    for sender in ("AD-BOBTXN", "VM-HDFCBK", "PAYTMB", "JD-SBIUPI-S"):
        parse_sms(sender, body)


def test_bank_specific_parser_failure_falls_back_to_generic() -> None:
    parsed = parse_sms("AD-BOBTXN", "Paid Rs.120 to ZOMATO. UPI Ref No 628900000005 A/c XX1234")
    assert isinstance(parsed, ParsedTxn)
    assert (parsed.bank, parsed.amount_paise, parsed.counterparty) == ("bob", 12000, "ZOMATO")


@pytest.mark.parametrize(
    ("sender", "normalised"),
    [
        ("AD-BOBTXN", "BOBTXN"),
        ("VM-HDFCBK", "HDFCBK"),
        ("JD-SBIUPI-S", "SBIUPI"),
        ("BOBSMS", "BOBSMS"),
        ("bp-bobtxn-t", "BOBTXN"),
        (" AX-AXISBK-P ", "AXISBK"),
        ("TX-ICICIB-G", "ICICIB"),
    ],
)
def test_normalize_sender(sender: str, normalised: str) -> None:
    assert normalize_sender(sender) == normalised


@pytest.mark.parametrize(
    ("sender", "bank"),
    [
        ("AD-BOBTXN", "bob"),
        ("BOBSMS", "bob"),
        ("VM-BOBXYZ", "bob"),
        ("AD-BARODA", "bob"),
        ("VM-HDFCBK", "hdfc"),
        ("JD-SBIUPI-S", "sbi"),
        ("ATMSBI", "sbi"),
        ("VM-ICICIT", "icici"),
        ("AXISMR", "axis"),
        ("KOTAKM", "kotak"),
        ("CANARA", "canara"),
        ("AD-PHONPE", "upi"),
        ("BHIMUP", "upi"),
        ("AD-SHOPXX", None),
        ("+919999999999", None),
        ("", None),
    ],
)
def test_bank_for_sender(sender: str, bank: str | None) -> None:
    assert bank_for_sender(sender) == bank


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        ("Rs.1,234.50 debited", 123450),
        ("Rs 500 spent", 50000),
        ("INR 12,000.00 credited", 1200000),
        ("₹250 paid", 25000),
        ("Rs.2,00,000.00", 20000000),
        ("rs.99", 9900),
        ("Rs.0.5", 50),
        ("no amount here", None),
        ("Mars 500", None),
    ],
)
def test_parse_amount(text: str, paise: int | None) -> None:
    assert parse_amount(text) == paise


@pytest.mark.parametrize(
    ("text", "mask"),
    [
        ("debited from A/c XX1234 on", "XX1234"),
        ("A/c XXXXXX1234", "XX1234"),
        ("A/c *1234", "XX1234"),
        ("a/c no. ...1234", "XX1234"),
        ("Card ending 1234 for", "XX1234"),
        ("account **1234 to", "XX1234"),
        ("Acct xx234 debited", "XX234"),
        ("A/c 123456789012", "XX9012"),
        ("A/C X1234-debited", "XX1234"),
        ("Dear customer, call 18005700", None),
    ],
)
def test_account_mask(text: str, mask: str | None) -> None:
    assert find_account_mask(text) == mask


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        ("Avl Bal Rs.12,345.67", 1234567),
        ("Avl bal:INR 5,000.00", 500000),
        ("Available Balance: Rs 100", 10000),
        ("Bal Rs.250.50", 25050),
        ("Total Bal:Rs.10,500.00CR. Avlbl Amt:Rs.9,000.00(05-10-2026 10:15:32)", 900000),
        ("Total Bal:Rs.10,500.00CR", 1050000),
        ("Clr Bal Rs.4,201.00", 420100),
        ("Total Avail.Bal INR 5,000.00.", 500000),
        ("Avl Bal Rs.1,500.00 Dr", -150000),
        ("Avl Bal Rs.-200.00", -20000),
        ("Avl Bal for A/c XX1234 is Rs.4,201.00 as on", 420100),
        ("Avl Limit Rs.47,650.00", None),
        ("Balance.", None),
    ],
)
def test_find_balance(text: str, paise: int | None) -> None:
    assert find_balance(text) == paise


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("on 05-10-26 to", date(2026, 10, 5)),
        ("on 05-10-2026", date(2026, 10, 5)),
        ("on 05/10/26", date(2026, 10, 5)),
        ("on 05Oct26 trf", date(2026, 10, 5)),
        ("on 05-Oct-2026", date(2026, 10, 5)),
        ("on 05-OCT-26", date(2026, 10, 5)),
        ("on 2026-10-05", date(2026, 10, 5)),
        ("on 31-02-26 and 05-10-26", date(2026, 10, 5)),
        ("on 05-13-26", None),
        ("no date 10:15:32", None),
    ],
)
def test_find_date(text: str, expected: date | None) -> None:
    assert find_date(text) == expected


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("(UPI Ref No 627812345678)", "627812345678"),
        ("Ref no. 628012345678.", "628012345678"),
        ("NEFT UTR SBIN526275000123 from", "SBIN526275000123"),
        ("UTR: ICIC52026100500123.", "ICIC52026100500123"),
        ("RRN 612345678901", "612345678901"),
        ("IMPS Ref no. 628400000002", "628400000002"),
        ("thru UPI/627812345679 by", "627812345679"),
        ("transaction reference number is 627900000001.", "627900000001"),
        ("Ref No is missing", None),
    ],
)
def test_find_reference(text: str, ref: str | None) -> None:
    assert find_reference(text) == ref


@pytest.mark.parametrize(
    "body",
    [
        "Request for RTGS/ NEFT of Rs. 50005.00 in favour of Beneficiary 12345678901 has been "
        "received. If not requested by you, contact base branch immediately - Bank of Baroda",
        "Request for NEFT of Rs. 50005.00 in favour of Beneficiary 12345678901 has been "
        "verified successfully - Bank of Baroda",
        "Request for RTGS/NEFT of Rs. 50005.00 in favour of Beneficiary 12345678901 has been "
        "verified successfully - Bank of Baroda",
        "Amount of Rs. 50005.00 is Credited to Beneficiary A/c on 19-09-2026 13:09:35 through "
        "NEFT for your UTR No. BARBT12345678901 -Bank of Baroda",
    ],
)
def test_bob_transfer_status_notices_are_not_transactions(body: str) -> None:
    assert parse_sms("AD-BOBTXN", body) is None


@pytest.mark.parametrize(
    ("body", "direction", "amount", "channel", "reference", "balance"),
    [
        (
            "Rs.60070 Credited to A/c ...1234 from:11112222333344 D. Total Bal:Rs.75000.04CR. "
            "Avlbl Amt:Rs.75000.04(19-09-2026 10:29:30) - Bank of Baroda",
            "credit",
            6007000,
            "other",
            None,
            7500004,
        ),
        (
            "Rs.50005 Debited to A/c ...1234 for NEFT to SOME NAME UTR BARBT12345678901. "
            "Total Bal:Rs.39977.64CR. Avlbl Amt:Rs.39977.64(19-09-2026 12:45:17). "
            "Not you? Call 18005700-BOB",
            "debit",
            5000500,
            "neft",
            "BARBT12345678901",
            3997764,
        ),
        (
            "Rs.500 Credited to A/c ...1234 thru NEFT UTR AXOBU12345678 by SOME NAME "
            "Total Bal:Rs.999.99CR. Avlbl Amt:Rs.999.99(01-10-2026 10:00:00) - Bank of Baroda",
            "credit",
            50000,
            "neft",
            "AXOBU12345678",
            99999,
        ),
        (
            "Rs.17.4 transferred from A/c ...1234 to:SOME NAME Total Bal:Rs.39977.64CR. "
            "Avlbl Amt:Rs.39977.64(19-09-2026 12:45:17) - Bank of Baroda",
            "debit",
            1740,
            "other",
            None,
            3997764,
        ),
        (
            "Rs.500 deposited in cash to A/c ...1234. Total Bal:Rs.1500.00CR. "
            "Avlbl Amt:Rs.1500.00(19-09-2026 12:45:17) - Bank of Baroda",
            "credit",
            50000,
            "cash",
            None,
            150000,
        ),
    ],
)
def test_bob_real_transfer_shapes_still_parse(
    body: str,
    direction: str,
    amount: int,
    channel: str,
    reference: str | None,
    balance: int,
) -> None:
    parsed = parse_sms("AD-BOBTXN", body)
    assert isinstance(parsed, ParsedTxn)
    assert (
        parsed.direction,
        parsed.amount_paise,
        parsed.channel,
        parsed.reference,
        parsed.balance_paise,
        parsed.account_mask,
    ) == (direction, amount, channel, reference, balance, "XX1234")
