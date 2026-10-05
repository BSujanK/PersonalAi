"""Deterministic mail classification. Pure: no I/O, no model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from agent.connectors.gmail import MailMessage

Category = Literal["important", "normal", "promo", "spam"]
Source = Literal["sender_rule", "gmail", "rule", "llm", "feedback"]

CATEGORY_VALUES: tuple[Category, ...] = ("important", "normal", "promo", "spam")

_KEYWORDS = re.compile(
    r"\b(?:deadline|due|exam|examination|interview|fee|fees|placement|offer letter|result"
    r"|admit card|hall ticket|assignment|submission|urgent)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuleContext:
    vip_senders: frozenset[str]
    college_domains: frozenset[str]
    has_replied: bool
    sender_rule: Category | None


def as_category(value: str | None) -> Category | None:
    for category in CATEGORY_VALUES:
        if value == category:
            return category
    return None


def _domain_matches(addr: str, domains: frozenset[str]) -> bool:
    domain = addr.rpartition("@")[2]
    return any(domain == d or domain.endswith(f".{d}") for d in domains)


def classify_by_rules(msg: MailMessage, ctx: RuleContext) -> tuple[Category, Source, str] | None:
    """Return (category, source, reason code) or None when the rules cannot decide."""
    sender = msg.from_addr.lower()
    if ctx.sender_rule is not None:
        return ctx.sender_rule, "sender_rule", "sender_rule"
    labels = set(msg.label_ids)
    if "SPAM" in labels:
        return "spam", "gmail", "gmail_spam"
    if "CATEGORY_PROMOTIONS" in labels:
        return "promo", "gmail", "gmail_promotions"
    if "CATEGORY_SOCIAL" in labels:
        return "normal", "gmail", "gmail_social"
    if sender in ctx.vip_senders:
        return "important", "rule", "vip"
    if _domain_matches(sender, ctx.college_domains):
        return "important", "rule", "college_domain"
    if msg.list_unsubscribe and not ctx.has_replied:
        return "promo", "rule", "list_unsubscribe"
    if _KEYWORDS.search(msg.subject):
        return "important", "rule", "keyword"
    if ctx.has_replied:
        return "normal", "rule", "replied_before"
    return None
