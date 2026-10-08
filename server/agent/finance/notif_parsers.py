"""Payment-app notifications. The phone uploads them through the SMS pipeline under the reserved
sender names below; the body is ``"<title>\\n<text>"``. Pure: no I/O, logs nothing about the
content. Anything that is not a plain, completed payment parses to None."""

from __future__ import annotations

import re

from agent.finance.model import (
    APP_BOBWORLD,
    APP_GPAY,
    APP_PHONEPE,
    NOTIFICATION_SENDERS,
    Direction,
    Parsed,
    ParsedTxn,
)
from agent.finance.sms_parsers import bob, parse_sms
from agent.finance.sms_parsers.common import (
    AMT_GROUP,
    MAX_COUNTERPARTY,
    normalize,
    to_paise,
)

__all__ = [
    "APP_BOBWORLD",
    "APP_GPAY",
    "APP_PHONEPE",
    "NOTIFICATION_SENDERS",
    "parse_message",
    "parse_notification",
]

# Failed, pending, promotional and reminder notifications never describe settled money.
_REJECT = re.compile(
    r"\b(?:fail\w*|pending|declin\w*|revers\w*|cashback|reward\w*|offer\w*|request\w*|due"
    r"|bill\w*|reminder\w*|scratch\w*|coupon\w*)\b",
    re.IGNORECASE,
)

# A VPA or a person's name, up to an optional full stop that ends the sentence.
_PARTY = r"(?P<cp>[A-Za-z0-9][A-Za-z0-9 .'@_-]*?)\.?"
_SENT = re.compile(rf"^{AMT_GROUP}\s+has\s+been\s+sent\s+to\s+{_PARTY}$", re.IGNORECASE)
_PHONEPE_RECEIVED = (
    re.compile(rf"^Received\s+{AMT_GROUP}\s+from\s+{_PARTY}$", re.IGNORECASE),
    re.compile(rf"^{AMT_GROUP}\s+received\s+from\s+{_PARTY}$", re.IGNORECASE),
)
_GPAY_RECEIVED = re.compile(rf"^{_PARTY}\s+paid\s+you\s+{AMT_GROUP}$", re.IGNORECASE)


def _split(body: str) -> tuple[str, str]:
    title, _, text = body.partition("\n")
    return (title, text) if text else ("", title)


def _txn(direction: Direction, match: re.Match[str]) -> ParsedTxn | None:
    amount = to_paise(match.group("amt"))
    name = match.group("cp").strip()[:MAX_COUNTERPARTY]
    if amount is None or amount <= 0 or not name:
        return None
    return ParsedTxn(
        bank="upi",
        account_mask=None,
        direction=direction,
        amount_paise=amount,
        channel="upi",
        counterparty=name,
        reference=None,
        txn_date=None,
        balance_paise=None,
    )


def _phonepe(text: str) -> ParsedTxn | None:
    sent = _SENT.match(text)
    if sent:
        return _txn("debit", sent)
    for template in _PHONEPE_RECEIVED:
        received = template.match(text)
        if received:
            return _txn("credit", received)
    return None


def _gpay(text: str) -> ParsedTxn | None:
    received = _GPAY_RECEIVED.match(text)
    return _txn("credit", received) if received else None


def parse_notification(sender: str, body: str) -> ParsedTxn | None:
    """The payment a notification reports, or None for anything else (including unknown
    senders). PhonePe and Google Pay are read by strict templates; Bank of Baroda's own app
    sends the same wording as its SMS, so the SMS parser reads its text."""
    if sender not in NOTIFICATION_SENDERS:
        return None
    title, text = _split(body)
    if sender == APP_BOBWORLD:
        parsed = bob.parse(text)
        return parsed if isinstance(parsed, ParsedTxn) else None
    if _REJECT.search(title) or _REJECT.search(text):
        return None
    text = normalize(text)
    return _phonepe(text) if sender == APP_PHONEPE else _gpay(text)


def parse_message(sender: str, body: str) -> Parsed | None:
    """The one parser the ingest uses: notification senders by template, the rest as SMS."""
    if sender in NOTIFICATION_SENDERS:
        return parse_notification(sender, body)
    return parse_sms(sender, body)
