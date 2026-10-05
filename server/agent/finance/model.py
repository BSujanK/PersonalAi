"""Parsed bank messages. Amounts are integer paise; accounts are masked to their last 4 digits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Direction = Literal["debit", "credit"]
Channel = Literal["upi", "card", "atm", "neft", "imps", "rtgs", "netbanking", "cash", "other"]
Bank = Literal["bob", "hdfc", "sbi", "icici", "axis", "kotak", "canara", "upi"]

BANKS: tuple[Bank, ...] = ("bob", "hdfc", "sbi", "icici", "axis", "kotak", "canara", "upi")


@dataclass(frozen=True)
class ParsedTxn:
    bank: Bank
    account_mask: str | None  # "XX1234", or None when the message names no account
    direction: Direction
    amount_paise: int  # always > 0
    channel: Channel
    counterparty: str | None  # VPA, merchant or payee name as written in the message
    reference: str | None  # UPI ref / UTR / RRN, digits or alphanumerics only
    txn_date: date | None  # the date printed in the message, if any
    balance_paise: int | None  # "Avl Bal" figure, if the message carries one


@dataclass(frozen=True)
class ParsedBalance:
    """A balance-only message (no transaction), e.g. a balance enquiry reply."""

    bank: Bank
    account_mask: str
    balance_paise: int


Parsed = ParsedTxn | ParsedBalance
