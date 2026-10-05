"""Canara Bank SMS (CANBNK, CANARA)."""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_TEMPLATES = (
    # An amount of INR 250.00 has been DEBITED to your account XXX234 on 05/10/2026 Total Avail.Bal
    re.compile(
        rf"An\s+amount\s+of\s+{AMT_GROUP}\s+has\s+been\s+{DIR_GROUP}\s+(?:to|from)\s+your\s+account",
        re.IGNORECASE,
    ),
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\b", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("canara", body, _TEMPLATES)
