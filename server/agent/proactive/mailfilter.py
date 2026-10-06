"""Newsletter and promotion detection for the deadline scan. Pure: no I/O, no model.

A market newsletter once became a calendar event because "this week" and a date sat next to a
deadline-like word. Bulk mail from senders the owner does not trust is not searched for deadlines
at all. Trusted senders (VIPs, college domains) are never filtered.
"""

from __future__ import annotations

import re
from collections.abc import Collection

BULK_LABELS = frozenset({"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"})

_APOSTROPHE = r"['\u2019]"
_NEWSLETTER_TEXT = re.compile(
    r"\b(?:unsubscribe"
    r"|newsletter"
    r"|view (?:this email|it|this) in (?:your )?browser"
    r"|manage (?:your )?(?:email )?(?:preferences|subscriptions)"
    r"|(?:weekly|daily|monthly) (?:digest|roundup|recap|briefing|wrap)"
    rf"|you(?:{_APOSTROPHE}re| are) receiving this (?:email|because)"
    r"|market (?:wrap|update|outlook|recap))\b",
    re.IGNORECASE,
)
_BULK_LOCAL_PART = re.compile(
    r"(?:newsletters?|news|digest|marketing|promo(?:s|tions)?|offers|deals|mailer|campaigns?)",
    re.IGNORECASE,
)


def is_trusted_sender(
    from_addr: str, vip_senders: Collection[str], college_domains: Collection[str]
) -> bool:
    """The same test as ``agent.mail.rules``: an exact (lower-case) VIP address, or an address at
    a college domain or one of its subdomains."""
    sender = from_addr.lower()
    if sender in vip_senders:
        return True
    domain = sender.rpartition("@")[2]
    return any(domain == d or domain.endswith(f".{d}") for d in college_domains)


def is_bulk_mail(
    from_addr: str,
    subject: str,
    body: str,
    label_ids: Collection[str],
    list_unsubscribe: bool,
) -> str | None:
    """A reason code when the mail looks like a newsletter or promotion, else ``None``.

    The codes are ``list_unsubscribe``, ``bulk_label``, ``newsletter_text`` and ``bulk_sender``.
    This does not know about trusted senders: callers check ``is_trusted_sender`` first.
    """
    if list_unsubscribe:
        return "list_unsubscribe"
    if BULK_LABELS & set(label_ids):
        return "bulk_label"
    if _NEWSLETTER_TEXT.search(subject) or _NEWSLETTER_TEXT.search(body):
        return "newsletter_text"
    if _BULK_LOCAL_PART.fullmatch(from_addr.rpartition("@")[0].strip()):
        return "bulk_sender"
    return None
