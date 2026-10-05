"""Axis Bank SMS (AXISBK, AXISMR)."""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_TEMPLATES = (
    # INR 500.00 debited from A/c no. XX1234 on 05-10-26 15:20:11 UPI/P2M/6274.../SHOP NAME.
    re.compile(
        rf"{AMT_GROUP}\s+{DIR_GROUP}\s+from\s+A/c\s+no\.?\s*\S+\s+on\s+.*?"
        r"(?:UPI|IMPS)/P2[AM]/\d+/(?P<cp>[^./]+?)\.",
        re.IGNORECASE,
    ),
    # INR 5000.00 credited to A/c no. XX1234 on ... Info: NEFT-AXISN5...-BRIGHT SOLUTIONS.
    re.compile(
        rf"{AMT_GROUP}\s+{DIR_GROUP}\s+to\s+A/c\s+no\.?\s*\S+\s+on\s+.*?"
        r"Info:?\s*NEFT-[A-Z0-9]+-(?P<cp>[A-Za-z ]+?)\.",
        re.IGNORECASE,
    ),
    # Spent Card no. XX5678 INR 499.00 07-10-26 15:20:11 AMAZON Avl Lmt INR 50,000.00
    re.compile(
        rf"(?P<dir>Spent)\s+Card\s+no\.?\s*\S+\s+{AMT_GROUP}\s+\S+\s+\d{{2}}:\d{{2}}:\d{{2}}\s+"
        r"(?P<cp>.+?)\s+Avl\s+Lmt",
        re.IGNORECASE,
    ),
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\b", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("axis", body, _TEMPLATES)
