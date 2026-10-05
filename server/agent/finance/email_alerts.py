"""Bank transaction-alert emails. Pure: the sender domain picks the bank, the SMS helpers read
the body. Logs nothing about the content."""

from __future__ import annotations

import re
from collections.abc import Mapping
from email.utils import parseaddr

from agent.finance.model import Bank, ParsedTxn
from agent.finance.sms_parsers.common import build

DEFAULT_BANK_DOMAINS: Mapping[str, Bank] = {
    "bankofbaroda.co.in": "bob",
    "bankofbaroda.com": "bob",
    "bobibanking.com": "bob",
    "hdfcbank.net": "hdfc",
    "hdfcbank.com": "hdfc",
    "sbi.co.in": "sbi",
    "icicibank.com": "icici",
    "axisbank.com": "axis",
    "kotak.com": "kotak",
    "canarabank.com": "canara",
}

_NON_TXN_SUBJECT = re.compile(r"\bstatement\b", re.IGNORECASE)


def _bank_for_address(from_addr: str, bank_domains: Mapping[str, Bank]) -> Bank | None:
    domain = parseaddr(from_addr)[1].rpartition("@")[2].strip().lower().rstrip(".")
    if not domain:
        return None
    for known, bank in bank_domains.items():
        if domain == known or domain.endswith(f".{known}"):
            return bank
    return None


def parse_alert_email(
    from_addr: str,
    subject: str,
    body: str,
    bank_domains: Mapping[str, Bank] = DEFAULT_BANK_DOMAINS,
) -> ParsedTxn | None:
    bank = _bank_for_address(from_addr, bank_domains)
    if bank is None or _NON_TXN_SUBJECT.search(subject):
        return None
    parsed = build(bank, body, email=True)
    return parsed if isinstance(parsed, ParsedTxn) else None
