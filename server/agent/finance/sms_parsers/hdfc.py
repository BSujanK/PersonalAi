"""HDFC Bank SMS (HDFCBK, HDFCBN, HDFCBANK)."""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_TEMPLATES = (
    # Sent Rs.1250.00 From HDFC Bank A/c *1234 To GROCER STORE On 05/10/26 Ref 6271...
    re.compile(
        rf"\bSent\s+{AMT_GROUP}\s+From\s+HDFC\s+Bank\s+A/c\s+\S+\s+To\s+(?P<cp>[A-Z][A-Za-z' ]+)"
    ),
    # Update! INR 15,000.00 deposited in HDFC Bank A/c XX1234 on 09-OCT-26 for NEFT Cr-IFSC-NAME-...
    re.compile(
        rf"{AMT_GROUP}\s+{DIR_GROUP}\s+in\s+HDFC\s+Bank\s+A/c\s+\S+\s+on\s+\S+\s+for\s+NEFT\s+Cr-"
        r"[A-Z0-9]+-(?P<cp>[A-Za-z0-9 &]+?)-",
        re.IGNORECASE,
    ),
    # Rs. 1,250.00 debited from a/c **1234 ... / Credit Alert! Rs.5000.00 credited to HDFC Bank A/c
    re.compile(rf"{AMT_GROUP}\s+(?:is\s+)?{DIR_GROUP}\b", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("hdfc", body, _TEMPLATES)
