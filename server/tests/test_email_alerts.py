from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from agent.finance.email_alerts import DEFAULT_BANK_DOMAINS, parse_alert_email

FIXTURES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "bank_alert_emails.json").read_text(encoding="utf-8")
)
BODY = "Rs.250.00 has been debited from your account XX1234 to VPA shop@okicici on 05-10-26."


def _address(local: str, domain: str) -> str:
    return local + "@" + domain


def _actual(case: dict[str, Any]) -> dict[str, Any] | None:
    parsed = parse_alert_email(
        _address(case["from_local"], case["from_domain"]), case["subject"], case["body"]
    )
    if parsed is None:
        return None
    fields = asdict(parsed)
    fields["txn_date"] = parsed.txn_date.isoformat() if parsed.txn_date else None
    return {"kind": "txn", **fields}


@pytest.mark.parametrize("case", FIXTURES, ids=[f"{i:02d}" for i in range(len(FIXTURES))])
def test_fixture_exact_match(case: dict[str, Any]) -> None:
    assert _actual(case) == case["expected"]


def test_fixture_coverage() -> None:
    assert len(FIXTURES) >= 12
    assert FIXTURES[0]["expected"]["bank"] == "bob"
    assert any(case["expected"] is None for case in FIXTURES)


def test_every_default_domain_maps_to_its_bank() -> None:
    for domain, bank in DEFAULT_BANK_DOMAINS.items():
        parsed = parse_alert_email(_address("alerts", domain), "Alert", BODY)
        assert parsed is not None
        assert parsed.bank == bank


@pytest.mark.parametrize(
    "domain", ["hdfcbank.net", "HDFCBANK.NET", "alerts.hdfcbank.net", "mail.alerts.hdfcbank.net"]
)
def test_exact_and_subdomain_domains_match(domain: str) -> None:
    parsed = parse_alert_email(_address("alerts", domain), "Alert", BODY)
    assert parsed is not None
    assert parsed.bank == "hdfc"


@pytest.mark.parametrize(
    "domain", ["hdfcbank.net.example.com", "xhdfcbank.net", "hdfcbank.net.evil.example", "net", ""]
)
def test_lookalike_domains_rejected(domain: str) -> None:
    assert parse_alert_email(_address("alerts", domain), "Alert", BODY) is None


def test_display_name_form_is_accepted() -> None:
    sender = "HDFC Bank <" + _address("alerts", "hdfcbank.net") + ">"
    assert parse_alert_email(sender, "Alert", BODY) is not None


def test_custom_bank_domains() -> None:
    sender = _address("alerts", "mail.example.org")
    assert parse_alert_email(sender, "Alert", BODY) is None
    parsed = parse_alert_email(sender, "Alert", BODY, {"example.org": "kotak"})
    assert parsed is not None
    assert parsed.bank == "kotak"


def test_garbage_returns_none() -> None:
    sender = _address("alerts", "hdfcbank.net")
    assert parse_alert_email(sender, "", "") is None
    assert parse_alert_email("not an address", "x", BODY) is None
    assert parse_alert_email(sender, "x", "\x00 Rs. ### debited") is None
