"""Shared helpers for the bank SMS and alert-email parsers. Pure: no I/O, never raises."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from agent.finance.model import (
    NOTIFICATION_SENDERS,
    Bank,
    Channel,
    Direction,
    Parsed,
    ParsedBalance,
    ParsedTxn,
)

MAX_TEXT = 2000
MAX_COUNTERPARTY = 64

_NUM = r"\d[\d,]*(?:\.\d+)?"
_CCY = r"(?<![A-Za-z])(?:Rs\.?|INR|₹)"

# Template fragments the bank modules build their patterns from.
AMT_GROUP = rf"{_CCY}\s*(?P<amt>{_NUM})"
DIR_GROUP = r"(?P<dir>debited|credited|withdrawn|spent|sent|received|deposited)"

# --- sender -> bank ----------------------------------------------------------------------------

_SENDER_PREFIX = re.compile(r"^[A-Z]{2}-(?=.)")
_SENDER_SUFFIX = re.compile(r"-[STPG]$")

_SENDER_BANKS: dict[str, Bank] = {
    **dict.fromkeys(("BOBTXN", "BOBSMS", "BOBCRD", "BARODA", "BOBUPI"), "bob"),
    **dict.fromkeys(("HDFCBK", "HDFCBN", "HDFCBANK"), "hdfc"),
    **dict.fromkeys(("SBIBNK", "SBIINB", "SBIUPI", "SBIPSG", "ATMSBI", "CBSSBI"), "sbi"),
    **dict.fromkeys(("ICICIB", "ICICIT", "ICICIO"), "icici"),
    **dict.fromkeys(("AXISBK", "AXISMR"), "axis"),
    **dict.fromkeys(("KOTAKB", "KOTAKM"), "kotak"),
    **dict.fromkeys(("CANBNK", "CANARA"), "canara"),
    **dict.fromkeys(("PAYTMB", "PHONPE", "GPAY", "BHIMUP"), "upi"),
}


def known_senders() -> list[str]:
    """Normalised sender IDs the parsers recognise; the phone uses them as its SMS filter."""
    return sorted(_SENDER_BANKS)


def normalize_sender(sender: str) -> str:
    """`AD-BOBTXN` / `JD-SBIUPI-S` / `bobsms` -> `BOBTXN` / `SBIUPI` / `BOBSMS`."""
    name = sender.strip().upper()
    name = _SENDER_PREFIX.sub("", name, count=1)
    return _SENDER_SUFFIX.sub("", name, count=1)


def bank_for_sender(sender: str) -> Bank | None:
    if sender in NOTIFICATION_SENDERS:  # exact match: a payment-app notification, not an SMS
        return NOTIFICATION_SENDERS[sender]
    name = normalize_sender(sender)
    bank = _SENDER_BANKS.get(name)
    if bank is not None:
        return bank
    return "bob" if name.startswith("BOB") else None


# --- field helpers -----------------------------------------------------------------------------

_AMOUNT = re.compile(rf"{_CCY}\s*({_NUM})", re.IGNORECASE)
# SBI-style "debited by 250.0": the figure sits right after the verb, currency optional.
_VERB_AMOUNT = re.compile(
    rf"\b(?:debited|credited|withdrawn|spent|paid|sent|received|deposited)\s*"
    rf"(?:(?:by|with|for|of)\s+)?(?:{_CCY}\s*)?({_NUM})",
    re.IGNORECASE,
)
_FIGURE_LABEL = re.compile(r"(?:bal(?:ance)?|amt|lmt|limit|avl|avail(?:able)?)\W*$", re.IGNORECASE)


def to_paise(figure: str) -> int | None:
    try:
        value = Decimal(figure.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return int((value * 100).to_integral_value())


def parse_amount(text: str) -> int | None:
    """First currency-marked amount in `text` as integer paise (`Rs.1,234.50` -> 123450)."""
    match = _AMOUNT.search(text)
    return to_paise(match.group(1)) if match else None


_MASK_PATTERNS = (
    re.compile(
        r"(?:\b(?:a/c|ac(?:ct)?|account|card)\b(?:\s*(?:no\.?|number))?|\bending(?:\s+(?:with|in))?)"
        r"\s*[:\-]?\s*(?:[Xx*.]+\s*)?(\d{3,})(?!\d)",
        re.IGNORECASE,
    ),
    re.compile(r"[Xx*]{2,}(\d{3,})(?!\d)"),
)


def find_account_mask(text: str) -> str | None:
    """Normalise any account/card hint to `XX` + its last 4 digits (3 when only 3 are shown)."""
    for pattern in _MASK_PATTERNS:
        match = pattern.search(text)
        if match:
            return "XX" + match.group(1)[-4:]
    return None


_CCY_BARE = r"(?:Rs\.?|INR|₹)"
_BAL_TAIL = (
    r"(?:\s+(?:for|in)\b.{0,40}?(?=\s(?:is|of)\s))?"
    r"(?:\s|:|=|\bis\b|\bof\b)*"
    rf"(?:{_CCY_BARE}\s*)?"
    r"(-?\s*\d[\d,]*(?:\.\d+)?)"
    r"\s*(CR|DR)?(?![A-Za-z])"
)
_BAL_PRIMARY = re.compile(
    r"\b(?:avl\.?\s*bal(?:ance)?|avlbl\.?\s*(?:amt|amount|bal(?:ance)?)"
    r"|avail(?:able)?\.?\s*(?:bal(?:ance)?|amt|amount)|c?lr\.?\s*bal(?:ance)?"
    r"|clear\s*bal(?:ance)?)" + _BAL_TAIL,
    re.IGNORECASE,
)
_BAL_SECONDARY = re.compile(r"\b(?:total\s*bal(?:ance)?|bal(?:ance)?)" + _BAL_TAIL, re.IGNORECASE)


def _balance_match(text: str) -> re.Match[str] | None:
    return _BAL_PRIMARY.search(text) or _BAL_SECONDARY.search(text)


def _signed_balance(match: re.Match[str]) -> int | None:
    paise = to_paise(match.group(1).replace("-", "").replace(" ", ""))
    if paise is None:
        return None
    negative = match.group(1).lstrip().startswith("-") or (match.group(2) or "").upper() == "DR"
    return -paise if negative else paise


def find_balance(text: str) -> int | None:
    """Available balance in paise; negative for `-` or `Dr` balances. Prefers Avl over Total."""
    match = _balance_match(text)
    return _signed_balance(match) if match else None


_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
# Also BoB's colon form "2026:10:05" (always year-first, four digits, so times never match).
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})([-:])(\d{2})\2(\d{2})(?!\d)")
_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})(?!\d)")
_DATE_MON = re.compile(r"(?<![\dA-Za-z])(\d{1,2})[-\s]?([A-Za-z]{3,9})[-\s]?(\d{4}|\d{2})(?!\d)")


def _make_date(year: str, month: int, day: str) -> date | None:
    y = int(year)
    try:
        return date(y + 2000 if y < 100 else y, month, int(day))
    except ValueError:
        return None


def find_date(text: str) -> date | None:
    """Earliest valid date in `text`: 05-10-26, 05/10/2026, 05Oct26, 05-Oct-2026, 2026-10-05."""
    found: list[tuple[int, date]] = []
    for m in _DATE_ISO.finditer(text):
        parsed = _make_date(m.group(1), int(m.group(3)), m.group(4))
        if parsed:
            found.append((m.start(), parsed))
    for m in _DATE_NUM.finditer(text):
        parsed = _make_date(m.group(3), int(m.group(2)), m.group(1))
        if parsed:
            found.append((m.start(), parsed))
    for m in _DATE_MON.finditer(text):
        month = _MONTHS.get(m.group(2)[:3].lower())
        parsed = _make_date(m.group(3), month, m.group(1)) if month else None
        if parsed:
            found.append((m.start(), parsed))
    return min(found, key=lambda item: item[0])[1] if found else None


_REF_VALUE = r"((?=[A-Z0-9]*\d)[A-Z0-9]{6,})"
_REF_PATTERNS = (
    re.compile(rf"\b(?:UTR|RRN)\s*(?:No\.?|Number)?\s*[:\-]?\s*{_REF_VALUE}", re.IGNORECASE),
    re.compile(
        r"\b(?:UPI|IMPS|NEFT|RTGS)\s*(?:Ref(?:erence)?\.?\s*(?:No\.?|Number|ID)?|Txn\s*(?:ID|No\.?))"
        rf"\s*(?:is|:|-)?\s*{_REF_VALUE}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bRef(?:erence)?\.?\s*(?:No\.?|Number|ID|#)?\s*(?:is|:|-)?\s*{_REF_VALUE}", re.IGNORECASE
    ),
    re.compile(
        r"\b(?:UPI|IMPS|NEFT|RTGS)[\s/:\-]+(?:[A-Z0-9]{2,5}/)?((?=[A-Z0-9]*\d)[A-Z0-9]{9,})",
        re.IGNORECASE,
    ),
)


def find_reference(text: str) -> str | None:
    """UPI ref / UTR / RRN / IMPS ref, alphanumerics only."""
    for pattern in _REF_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return None


# --- classification ----------------------------------------------------------------------------

_OTP = re.compile(
    r"\b(?:otp|one[\s-]*time\s*pass(?:word|code)?|do\s*not\s*share|never\s*share"
    r"|verification\s*code|cvv)\b",
    re.IGNORECASE,
)
_OTP_VALUE = re.compile(
    r"\b(?:otp|one[\s-]*time\s*password)\b\W+(?:is\W+)?\d{4,8}\b"
    r"|\b\d{4,8}\s+is\s+(?:your|the)\s+(?:otp|one[\s-]*time)",
    re.IGNORECASE,
)
_PROMO = re.compile(
    r"\b(?:pre-?approved|offers?|click|apply\s+now|congratulations|limited\s+period)\b",
    re.IGNORECASE,
)
_FAILED = re.compile(
    r"\b(?:fail(?:ed|ure)?|declined|unsuccessful|rejected|insufficient"
    r"|not\s+(?:successful|processed))\b",
    re.IGNORECASE,
)
_COLLECT = re.compile(
    r"\b(?:has\s+requested|requested\s+(?:money|Rs|INR|₹)|collect\s+request"
    r"|requests?\s+you\s+to\s+pay|payment\s+request|request(?:ing)?\s+(?:money|payment))",
    re.IGNORECASE,
)
# Status notices about an outgoing transfer request or a beneficiary-side credit: no money moved
# on this account, but "credited" and an amount would otherwise read as income.
_TRANSFER_NOTICE = re.compile(
    r"\brequest\s+for\b.{0,20}\b(?:rtgs|neft|imps)\b.*\bin\s+favou?r\s+of\b"
    r"|\bcredited\s+to\s+beneficiary\b|\bto\s+beneficiary\s+a/?c\b",
    re.IGNORECASE,
)
_REVERSAL = re.compile(r"\b(?:revers(?:ed|al)|refund(?:ed)?)\b", re.IGNORECASE)

_CARD_NAME = re.compile(r"\b(?:debit|credit)\s+card\b", re.IGNORECASE)
_CREDIT = re.compile(r"\b(?:credited|received|deposited|refunded)\b", re.IGNORECASE)
_DEBIT = re.compile(
    r"\b(?:debited|debit|spent|withdrawn|wdl|paid|purchase|sent|used\s+for"
    r"|(?:using|used)\s+(?:your\s+)?card|transferred\s+from)\b",
    re.IGNORECASE,
)


def is_rejected(text: str, *, email: bool = False) -> bool:
    """True for OTP, promo, failed/declined, collect-request, transfer-status notices and
    reversal-without-credit text.

    Emails routinely carry a "never share your OTP" footer, so for them only an actual OTP
    value counts.
    """
    otp = _OTP_VALUE if email else _OTP
    if otp.search(text) or _PROMO.search(text) or _FAILED.search(text) or _COLLECT.search(text):
        return True
    if _TRANSFER_NOTICE.search(text):
        return True
    return bool(_REVERSAL.search(text) and not _CREDIT.search(text))


def detect_direction(text: str) -> Direction | None:
    flat = _CARD_NAME.sub("card", text)
    credit = _CREDIT.search(flat)
    debit = _DEBIT.search(flat)
    if credit and debit:
        if _REVERSAL.search(flat):
            return "credit"
        return "credit" if credit.start() < debit.start() else "debit"
    if credit:
        return "credit"
    return "debit" if debit else None


_CHANNELS: tuple[tuple[Channel, re.Pattern[str]], ...] = (
    ("atm", re.compile(r"\bATM\b|\bwithdrawn\b|cash\s*wdl|\bwdl\b|cash\s*withdrawal", re.I)),
    ("cash", re.compile(r"cash\s*dep|deposited\s+in\s+cash", re.I)),
    # UPI also when a VPA-style address (name@bank, no dotted domain) is the only clue.
    ("upi", re.compile(r"\bUPI\b|\bVPA\b|[\w.-]+@[A-Za-z]{2,}(?![\w@-]|\.[A-Za-z])", re.I)),
    ("imps", re.compile(r"\bIMPS\b", re.I)),
    ("neft", re.compile(r"\bNEFT\b", re.I)),
    ("rtgs", re.compile(r"\bRTGS\b", re.I)),
    ("card", re.compile(r"\bcard\b|\bPOS\b|\bspent\b", re.I)),
    ("netbanking", re.compile(r"net\s*banking|\bIB\b|\bINB\b|internet\s*banking", re.I)),
)


def detect_channel(text: str) -> Channel:
    for channel, pattern in _CHANNELS:
        if pattern.search(text):
            return channel
    return "other"


# --- counterparty ------------------------------------------------------------------------------

_VPA = re.compile(
    r"(?<![\w.-])([A-Za-z0-9][A-Za-z0-9._-]+@[A-Za-z][A-Za-z0-9]+)(?![A-Za-z0-9]|\.[A-Za-z])"
)
_STOP_WORDS = frozenset(
    {
        *("on", "dt", "date", "ref", "refno", "upi", "via", "thru", "through", "using", "avl"),
        *("avlbl", "bal", "not", "if", "call", "imps", "neft", "rtgs", "total", "from", "to"),
        *("for", "by", "with", "is", "has", "was", "will", "and", "at", "in", "txn", "info"),
        *("transaction", "the"),
    }
)
_REJECT_FIRST = frozenset(
    {
        *("neft", "imps", "rtgs", "upi", "atm", "cash", "cheque", "transfer", "inb", "net"),
        *("vpa", "your", "you", "the", "a", "an", "info", "rs", "inr"),
    }
)
_NAME_BY_DIRECTION = {
    "debit": re.compile(r"(?i:\b(?:to|towards))\s+([A-Z][A-Za-z' ]{1,60})"),
    "credit": re.compile(r"(?i:\b(?:from|by))\s+([A-Z][A-Za-z' ]{1,60})"),
}
_MERCHANT = re.compile(r"(?i:\bat)\s+([A-Z][A-Za-z0-9 &'*_]{1,60})")


def clean_counterparty(raw: str) -> str | None:
    """Cut a captured phrase at the first stop word; reject empty, bank and rail names."""
    words: list[str] = []
    for word in raw.split():
        if word.lower() in _STOP_WORDS:
            break
        words.append(word)
    if not words or words[0].lower() in _REJECT_FIRST:
        return None
    name = " ".join(words)[:MAX_COUNTERPARTY].strip()
    return None if not name or "bank" in name.lower() else name


def find_counterparty(text: str, direction: Direction) -> str | None:
    vpa = _VPA.search(text)
    if vpa:
        return vpa.group(1)[:MAX_COUNTERPARTY]
    for pattern in (_NAME_BY_DIRECTION[direction], _MERCHANT):
        # Re-search one character on: a rejected "by IMPS" must not swallow "from NAME".
        match = pattern.search(text)
        while match:
            name = clean_counterparty(match.group(1))
            if name:
                return name
            match = pattern.search(text, match.start() + 1)
    return None


# --- assembly ----------------------------------------------------------------------------------


def normalize(text: str) -> str:
    return " ".join(text.split())[:MAX_TEXT]


def find_txn_amount(text: str) -> int | None:
    """The transaction amount: skips balance and limit figures."""
    balance = _balance_match(text)
    verb = _VERB_AMOUNT.search(text)
    if verb and not (balance and balance.start() <= verb.start(1) < balance.end()):
        return to_paise(verb.group(1))
    for match in _AMOUNT.finditer(text):
        if balance and balance.start() <= match.start() < balance.end():
            continue
        if _FIGURE_LABEL.search(text[max(0, match.start() - 20) : match.start()]):
            continue
        return to_paise(match.group(1))
    return None


def build(
    bank: Bank,
    body: str,
    *,
    direction: Direction | None = None,
    amount_paise: int | None = None,
    counterparty: str | None = None,
    email: bool = False,
) -> Parsed | None:
    """Assemble a ParsedTxn / ParsedBalance from free text, letting a template override fields."""
    text = normalize(body)
    if not text or is_rejected(text, email=email):
        return None
    mask = find_account_mask(text)
    balance = find_balance(text)
    direction = direction or detect_direction(text)
    if direction is None:
        if balance is not None and mask is not None:
            return ParsedBalance(bank=bank, account_mask=mask, balance_paise=balance)
        return None
    amount = amount_paise if amount_paise is not None else find_txn_amount(text)
    if amount is None or amount <= 0:
        return None
    channel = detect_channel(text)
    if counterparty is None and channel != "atm":
        counterparty = find_counterparty(text, direction)
    return ParsedTxn(
        bank=bank,
        account_mask=mask,
        direction=direction,
        amount_paise=amount,
        channel=channel,
        counterparty=counterparty[:MAX_COUNTERPARTY] if counterparty else None,
        reference=find_reference(text),
        txn_date=find_date(text),
        balance_paise=balance,
    )


# Direction abbreviations a bank template may capture as `dir` (e.g. BoB "Dr." / "Cr.").
# Only honoured inside a template match, never in generic detection.
_TEMPLATE_ABBREVIATIONS: dict[str, Direction] = {"dr": "debit", "cr": "credit"}


def _template_direction(word: str) -> Direction | None:
    return _TEMPLATE_ABBREVIATIONS.get(word.lower()) or detect_direction(word)


def from_templates(bank: Bank, body: str, templates: Sequence[re.Pattern[str]]) -> Parsed | None:
    """Run a bank's own message templates; the first that matches supplies direction,
    amount and counterparty (named groups `dir`, `amt`, `cp`), the rest is read generically."""
    text = normalize(body)
    for template in templates:
        match = template.search(text)
        if match is None:
            continue
        groups = match.groupdict()
        word = groups.get("dir")
        figure = groups.get("amt")
        cp = groups.get("cp")
        return build(
            bank,
            text,
            direction=_template_direction(word) if word else None,
            amount_paise=to_paise(figure) if figure else None,
            counterparty=clean_counterparty(cp) if cp else None,
        )
    return None
