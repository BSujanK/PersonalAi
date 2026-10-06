"""Outbound check: nothing that looks like the owner's personal data may leave in a web request.

The model only ever sees placeholders (``⟨ACCT_1⟩``), and web tool arguments are deliberately not
rehydrated, so a placeholder in an argument is a request to send something private. The text is
also run through the redactor: anything it would mask is refused rather than masked, because a
search for a masked value is useless and the model should rephrase.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from agent.core.redact import RedactionMap, Redactor

_PLACEHOLDER = re.compile(r"⟨[A-Z_]+_\d+⟩")
_ASCII_PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")
_REPHRASE = " Rephrase it without personal data (names, account numbers, addresses, codes)."


def _normalised(text: str) -> str:
    """The form the redactor matches against: NFKC, invisible format characters dropped."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf"
    )


def outbound_problem(text: str, owner_emails: Sequence[str]) -> str | None:
    """A fixed reason the text must not be sent to the internet, or ``None`` when it may.

    The reason never echoes the text. Checks run on the text as given and on its normalised
    form, so lookalike characters cannot disguise a value.
    """
    normalised = _normalised(text)
    for candidate in (text, normalised):
        if (
            "⟨" in candidate
            or "⟩" in candidate
            or _PLACEHOLDER.search(candidate)
            or _ASCII_PLACEHOLDER.search(candidate)
        ):
            return "the request contains a placeholder for private data." + _REPHRASE
    lowered = normalised.lower()
    for email in owner_emails:
        wanted = email.strip().lower()
        if wanted and wanted in lowered:
            return "the request contains the owner's email address." + _REPHRASE
    if Redactor(owner_emails).redact(normalised, RedactionMap()).text != normalised:
        return "the request contains text that looks like personal data." + _REPHRASE
    return None
