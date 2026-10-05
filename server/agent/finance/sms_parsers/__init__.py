"""Pure bank-SMS parsers. `parse_sms` returns None for anything that is not a bank transaction or
balance message (OTPs, promos, failed payments, collect requests, unknown senders)."""

from __future__ import annotations

from collections.abc import Callable

from agent.finance.model import Bank, Parsed
from agent.finance.sms_parsers import axis, bob, canara, generic_upi, hdfc, icici, kotak, sbi
from agent.finance.sms_parsers.common import bank_for_sender

__all__ = ["bank_for_sender", "parse_sms"]

_BANK_PARSERS: dict[Bank, Callable[[str], Parsed | None]] = {
    "bob": bob.parse,
    "hdfc": hdfc.parse,
    "sbi": sbi.parse,
    "icici": icici.parse,
    "axis": axis.parse,
    "kotak": kotak.parse,
    "canara": canara.parse,
}


def parse_sms(sender: str, body: str) -> Parsed | None:
    bank = bank_for_sender(sender)
    if bank is None:
        return None
    specific = _BANK_PARSERS.get(bank)
    if specific is not None:
        parsed = specific(body)
        if parsed is not None:
            return parsed
    return generic_upi.parse(body, bank)
