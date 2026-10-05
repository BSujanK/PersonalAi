"""State Bank of India SMS (SBIBNK, SBIINB, SBIUPI, SBIPSG, ATMSBI, CBSSBI).

SBI often omits the currency symbol: `A/C X1234 debited by 250.0 on date 05Oct26 trf to ...`.
"""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_NUM = r"\d[\d,]*(?:\.\d+)?"

_TEMPLATES = (
    # A/C X1234 debited by 250.0 on date 05Oct26 trf to RAHUL K Refno 6272...
    re.compile(
        rf"A/c\s+\S+?\s*-?\s*{DIR_GROUP}\s+(?:by|with)\s+(?:(?:Rs\.?|INR)\s*)?(?P<amt>{_NUM})",
        re.IGNORECASE,
    ),
    # Rs.499.00 spent on your SBI Card ending 5678 at SWIGGY on 09Oct26
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\s+on\s+your\s+SBI\s+Card\b", re.IGNORECASE),
    # Rs.2000.00 withdrawn at SBI ATM ... from A/c XXXX1234
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\b", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("sbi", body, _TEMPLATES)
