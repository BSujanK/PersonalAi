"""Kotak Mahindra Bank SMS (KOTAKB, KOTAKM)."""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_TEMPLATES = (
    # Sent Rs.250.00 from Kotak Bank AC X1234 to shop@okicici on 05-10-26.UPI Ref 6275...
    re.compile(
        rf"\b{DIR_GROUP}\s+{AMT_GROUP}\s+from\s+Kotak\s+Bank\s+AC\s+\S+\s+to\s+"
        r"(?P<cp>[A-Za-z0-9._-]+@[A-Za-z0-9]+)",
        re.IGNORECASE,
    ),
    # Received Rs.500.00 in your Kotak Bank AC X1234 from ritu@okaxis on 06-10-26.
    re.compile(
        rf"\b{DIR_GROUP}\s+{AMT_GROUP}\s+in\s+your\s+Kotak\s+Bank\s+AC\s+\S+\s+from\s+"
        r"(?P<cp>[A-Za-z0-9._-]+@[A-Za-z0-9]+)",
        re.IGNORECASE,
    ),
    re.compile(rf"\b{DIR_GROUP}\s+{AMT_GROUP}", re.IGNORECASE),
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\b", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("kotak", body, _TEMPLATES)
