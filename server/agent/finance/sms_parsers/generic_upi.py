"""Fallback parser for UPI app messages (Paytm, PhonePe, Google Pay, BHIM) and any bank text
the bank-specific parsers did not recognise. Reads the message by keyword rather than template."""

from __future__ import annotations

from agent.finance.model import Bank, Parsed
from agent.finance.sms_parsers.common import build


def parse(body: str, bank: Bank = "upi") -> Parsed | None:
    return build(bank, body)
