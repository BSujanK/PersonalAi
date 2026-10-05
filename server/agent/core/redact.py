"""Redaction of sensitive values before any text reaches the cloud LLM (CLAUDE.md rule 3).

Detection is one combined pass over the original text: each pattern, in priority order, claims
spans that do not overlap anything an earlier pattern already claimed. Replacement happens once at
the end, so placeholders are never re-scanned. Values are replaced by stable placeholders such as
``⟨CARD_1⟩`` that can be rehydrated locally from a per-conversation :class:`RedactionMap`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None

_TOKEN = object()
_OPEN = "⟨"
_CLOSE = "⟩"


class Redacted:
    """Text that has passed through the redactor. Only this module constructs it."""

    __slots__ = ("_text",)
    _text: str

    def __init__(self, text: str, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise TypeError("Redacted can only be created by agent.core.redact")
        object.__setattr__(self, "_text", text)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Redacted is immutable")

    @property
    def text(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"Redacted(<{len(self._text)} chars>)"


def from_model(text: str) -> Redacted:
    """Wrap text that originated from the model, unchanged.

    Safe because the model only ever saw redacted text: anything it emits is already in
    placeholder space, so there is no raw connector data in it to protect.
    """
    return Redacted(text, _token=_TOKEN)


class RedactionMap:
    """Placeholder bookkeeping for one conversation. Holds raw values: keep it local/encrypted."""

    def __init__(self) -> None:
        # placeholder -> (normalised value, first-seen surface form)
        self._entries: dict[str, tuple[str, str]] = {}
        self._index: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}

    def placeholder_for(self, kind: str, norm: str, surface: str) -> str:
        existing = self._index.get((kind, norm))
        if existing is not None:
            return existing
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        placeholder = f"{_OPEN}{kind}_{n}{_CLOSE}"
        self._entries[placeholder] = (norm, surface)
        self._index[(kind, norm)] = placeholder
        return placeholder

    def original(self, placeholder: str) -> str | None:
        entry = self._entries.get(placeholder)
        return entry[1] if entry else None

    def to_json(self) -> str:
        return json.dumps(
            {p: {"norm": norm, "orig": orig} for p, (norm, orig) in self._entries.items()},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, s: str) -> RedactionMap:
        rmap = cls()
        for placeholder, entry in json.loads(s).items():
            match = _PLACEHOLDER_RE.fullmatch(placeholder)
            if match is None:
                raise ValueError("malformed redaction map")
            kind, n = match.group(1), int(match.group(2))
            norm, orig = str(entry["norm"]), str(entry["orig"])
            rmap._entries[placeholder] = (norm, orig)
            rmap._index[(kind, norm)] = placeholder
            rmap._counters[kind] = max(rmap._counters.get(kind, 0), n)
        return rmap


_PLACEHOLDER_RE = re.compile(f"{_OPEN}([A-Z_]+)_(\\d+){_CLOSE}")

Span = tuple[int, int]

_KEYWORDS_RE = (
    r"(?:otp|one[- ]time password|verification code|security code|passcode|password|passwd|pwd"
    r"|mpin|pin|cvv|code)"
)

_SECRET_KEYWORD_DIGITS = re.compile(
    rf"\b{_KEYWORDS_RE}\b[^\d\n]{{0,25}}?(?<!\w)(?P<val>\d{{4,8}})(?!\w)", re.IGNORECASE
)
_SECRET_PASSWORD_TOKEN = re.compile(
    r"\b(?:password|passwd|pwd|passcode)\b"
    r"(?:[ \t]*[:=\-][ \t]*|[ \t]+(?:is|are)[ \t]+(?::[ \t]*)?)(?P<val>\S{4,})",
    re.IGNORECASE,
)
_SECRET_DIGITS_FIRST = re.compile(
    r"(?<!\w)(?P<val>\d{4,8})(?!\w)[^\d\n]{0,20}?\b(?:otp|code|password)\b", re.IGNORECASE
)
_UPI = re.compile(
    r"(?<![a-zA-Z0-9._-])[a-zA-Z0-9._-]{2,256}@[a-zA-Z][a-zA-Z0-9]{2,64}"
    r"(?![a-zA-Z0-9]|\.[a-zA-Z0-9])"
)
_DIGIT_RUN = re.compile(r"(?<!\d)\d+(?:[ -]\d+)*(?!\d)")
_DIGIT_GROUP = re.compile(r"\d+")
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}(?P<sep>[ -]?)\d{4}(?P=sep)\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.IGNORECASE)
_PHONE_IN = re.compile(r"(?<![\w+])(?:(?:\+?91|0)[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")
_PHONE_INTL = re.compile(r"(?<![\w+])\+\d{1,3}(?:[ -]?\d){7,12}(?!\d)")
_ACCT_LABELLED = re.compile(
    r"(?<!\w)(?:a/c|acct|account)(?:[ \t]+no\.?|[ \t]+number)?[\s:.\-]*(?P<val>[Xx*]*\d{3,})(?!\d)",
    re.IGNORECASE,
)
_ACCT_MASKED = re.compile(r"(?<![\w*])(?:[Xx*]{2,}|\*)\d{3,}(?!\d)")
# Any contiguous run of 9+ digits is treated as an account-like number, however long, so that
# nothing of that size can escape.
_ACCT_BARE = re.compile(r"(?<!\d)\d{9,}(?!\d)")
# Spaced/hyphenated groups of 3+ digits (2-digit groups are left alone so dates survive).
_ACCT_GROUPED = re.compile(r"(?<!\d)\d{3,}(?:[ -]\d{3,})+(?!\d)")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _finditer_group(pattern: re.Pattern[str], text: str, group: str | int = 0) -> Iterator[Span]:
    for m in pattern.finditer(text):
        yield m.span(group)


def _secret_spans(text: str) -> Iterator[Span]:
    for pattern in (_SECRET_KEYWORD_DIGITS, _SECRET_PASSWORD_TOKEN, _SECRET_DIGITS_FIRST):
        yield from _finditer_group(pattern, text, "val")


def _card_spans(text: str) -> Iterator[Span]:
    """Luhn-valid 13-19 digit sequences, possibly grouped by single spaces/hyphens."""
    for run in _DIGIT_RUN.finditer(text):
        groups = [
            (run.start() + g.start(), run.start() + g.end())
            for g in _DIGIT_GROUP.finditer(run.group())
        ]
        i = 0
        while i < len(groups):
            found: tuple[int, str] | None = None
            digits = ""
            for j in range(i, len(groups)):
                digits += text[groups[j][0] : groups[j][1]]
                if len(digits) > 19:
                    break
                if len(digits) >= 13 and _luhn_ok(digits):
                    found = (j, digits)  # keep extending: prefer the longest valid window
            if found is None:
                i += 1
                continue
            yield groups[i][0], groups[found[0]][1]
            i = found[0] + 1


def _grouped_acct_spans(text: str) -> Iterator[Span]:
    for m in _ACCT_GROUPED.finditer(text):
        if sum(c.isdigit() for c in m.group()) >= 9:
            yield m.span()


def _phone_spans(text: str) -> Iterator[Span]:
    yield from _finditer_group(_PHONE_IN, text)
    for m in _PHONE_INTL.finditer(text):
        if 8 <= sum(c.isdigit() for c in m.group()) <= 15:
            yield m.span()


def _digits_only(value: str) -> str:
    return re.sub(r"[ -]", "", value)


@dataclass(frozen=True)
class _Kind:
    name: str
    spans: Callable[[str], Iterable[Span]]
    normalise: Callable[[str], str]


def _plain(value: str) -> str:
    return value


def _acct_norm(value: str) -> str:
    return re.sub(r"[ \-]", "", value).lower()


# Priority order: earlier kinds win overlapping spans. EMAIL_SELF's spans are per-instance
# (they depend on the configured owner emails) and are inserted by Redactor.
_KINDS_BEFORE_SELF = (_Kind("SECRET", _secret_spans, _plain),)
_KINDS_AFTER_SELF = (
    _Kind("UPI", lambda t: _finditer_group(_UPI, t), str.lower),
    _Kind("CARD", _card_spans, _digits_only),
    _Kind("AADHAAR", lambda t: _finditer_group(_AADHAAR, t), _digits_only),
    _Kind("PAN", lambda t: _finditer_group(_PAN, t), str.upper),
    _Kind("IFSC", lambda t: _finditer_group(_IFSC, t), str.upper),
    _Kind("PHONE", _phone_spans, _digits_only),
    _Kind(
        "ACCT",
        lambda t: [
            *_finditer_group(_ACCT_LABELLED, t, "val"),
            *_finditer_group(_ACCT_MASKED, t),
            *_finditer_group(_ACCT_BARE, t),
            *_grouped_acct_spans(t),
        ],
        _acct_norm,
    ),
)


def _overlaps(claimed: list[Span], span: Span) -> bool:
    return any(span[0] < end and start < span[1] for start, end in claimed)


class Redactor:
    def __init__(self, owner_emails: Iterable[str] = ()) -> None:
        emails = sorted({e.strip().lower() for e in owner_emails if e.strip()}, key=len)
        self._self_re: re.Pattern[str] | None = None
        if emails:
            alternatives = "|".join(re.escape(e) for e in reversed(emails))
            self._self_re = re.compile(
                rf"(?<![a-zA-Z0-9._+-])(?:{alternatives})(?![a-zA-Z0-9_-]|\.[a-zA-Z0-9])",
                re.IGNORECASE,
            )
        self_kind = _Kind(
            "EMAIL_SELF",
            lambda t: _finditer_group(self._self_re, t) if self._self_re else (),
            str.lower,
        )
        self._kinds = (*_KINDS_BEFORE_SELF, self_kind, *_KINDS_AFTER_SELF)

    def _redact_str(self, text: str, rmap: RedactionMap) -> str:
        # Untrusted text must not be able to forge a placeholder that rehydration would expand.
        text = text.replace(_OPEN, "<").replace(_CLOSE, ">")
        claimed: list[Span] = []
        replacements: list[tuple[Span, str]] = []
        for kind in self._kinds:
            for span in kind.spans(text):
                if span[0] == span[1] or _overlaps(claimed, span):
                    continue
                claimed.append(span)
                surface = text[span[0] : span[1]]
                placeholder = rmap.placeholder_for(kind.name, kind.normalise(surface), surface)
                replacements.append((span, placeholder))
        out: list[str] = []
        pos = 0
        for (start, end), placeholder in sorted(replacements):
            out.append(text[pos:start])
            out.append(placeholder)
            pos = end
        out.append(text[pos:])
        return "".join(out)

    def redact(self, text: str, rmap: RedactionMap) -> Redacted:
        return Redacted(self._redact_str(text, rmap), _token=_TOKEN)

    def redact_obj(self, obj: JSON, rmap: RedactionMap) -> JSON:
        """Redact string values recursively; dict keys are left untouched."""
        if isinstance(obj, str):
            return self._redact_str(obj, rmap)
        if isinstance(obj, list):
            return [self.redact_obj(item, rmap) for item in obj]
        if isinstance(obj, dict):
            return {key: self.redact_obj(value, rmap) for key, value in obj.items()}
        return obj

    @staticmethod
    def rehydrate(text: str, rmap: RedactionMap) -> str:
        def restore(match: re.Match[str]) -> str:
            original = rmap.original(match.group(0))
            return match.group(0) if original is None else original

        return _PLACEHOLDER_RE.sub(restore, text)

    @staticmethod
    def rehydrate_obj(obj: JSON, rmap: RedactionMap) -> JSON:
        if isinstance(obj, str):
            return Redactor.rehydrate(obj, rmap)
        if isinstance(obj, list):
            return [Redactor.rehydrate_obj(item, rmap) for item in obj]
        if isinstance(obj, dict):
            return {key: Redactor.rehydrate_obj(value, rmap) for key, value in obj.items()}
        return obj


__all__ = ["JSON", "Redacted", "RedactionMap", "Redactor", "from_model"]
