"""ICICI Bank SMS (ICICIB, ICICIT, ICICIO)."""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_TEMPLATES = (
    # ICICI Bank Acct XX123 debited for Rs 1,500.00 on 05-Oct-26; RAHUL K credited. UPI:6273...
    re.compile(
        rf"Acct\s+\S+\s+(?P<dir>debited)\s+for\s+{AMT_GROUP}\s+on\s+\S+?;\s*"
        r"(?P<cp>[A-Za-z' ]+?)\s+credited",
        re.IGNORECASE,
    ),
    # Acct XX123 credited with Rs 2,000.00 on 06-Oct-26 from AMIT S.
    re.compile(rf"Acct\s+\S+\s+(?:is\s+)?{DIR_GROUP}\s+(?:for|with)\s+{AMT_GROUP}", re.IGNORECASE),
    # Rs 499.00 spent on ICICI Bank Card XX5678 ...
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\b", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("icici", body, _TEMPLATES)
