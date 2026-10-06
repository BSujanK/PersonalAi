"""Bank of Baroda SMS (BOBTXN, BOBSMS, BOBCRD, BARODA, BOBUPI).

BoB often prints both `Total Bal` and `Avlbl Amt`; the available amount is the balance we keep.
"""

from __future__ import annotations

import re

from agent.finance.model import Parsed
from agent.finance.sms_parsers.common import AMT_GROUP, DIR_GROUP, from_templates

_VPA = r"[A-Za-z0-9._-]+@[A-Za-z0-9]+"

_TEMPLATES = (
    # BoB UPI, the most common format (owner's phone, 2026-10):
    # Rs.149.00 Dr. from A/C XXXXXX1234 and Cr. to shop@okaxis. Ref:6278.. AvlBal:Rs..(2026:10:05)
    # "Dr." / "Cr." here are BoB's debit/credit abbreviations, recognised only in this exact
    # shape (generic detection would misread "Dr." in names).
    re.compile(
        rf"{AMT_GROUP}\s+(?P<dir>Dr)\.?\s+from\s+A/C\s+\S+\s+and\s+Cr\.?\s+to\s+"
        rf"(?P<cp>{_VPA}|[^.;]+?)\s*[.;]\s*Ref",
        re.IGNORECASE,
    ),
    # The mirror image for money in: Rs.500.00 Cr. to A/C XXXXXX1234 and Dr. from name@ybl. Ref:...
    re.compile(
        rf"{AMT_GROUP}\s+(?P<dir>Cr)\.?\s+to\s+A/C\s+\S+\s+and\s+Dr\.?\s+from\s+"
        rf"(?P<cp>{_VPA}|[^.;]+?)\s*[.;]\s*Ref",
        re.IGNORECASE,
    ),
    # Rs.250.00 debited from A/c XX1234 on 05-10-26 to VPA shop@okicici (UPI Ref No 6278...)
    re.compile(
        rf"{AMT_GROUP}\s+{DIR_GROUP}\s+from\s+(?:your\s+)?A/c\s+\S+\s+on\s+\S+\s+to\s+VPA\s+"
        rf"(?P<cp>{_VPA})",
        re.IGNORECASE,
    ),
    # Rs.500.00 Credited to A/c ...1234 thru UPI/6278... by name@ybl (or a payee name)
    re.compile(
        rf"{AMT_GROUP}\s+{DIR_GROUP}\s+(?:to\s+)?(?:your\s+)?A/c\s+\S+\s+thru\s+UPI/\w+\s+"
        rf"(?:by|to)\s+(?P<cp>{_VPA}|[A-Z][A-Za-z' ]+)",
        re.IGNORECASE,
    ),
    # Rs.2000 withdrawn from A/c XX1234 ... / Rs.99.00 debited from a/c no. ...1234 ...
    re.compile(rf"{AMT_GROUP}\s+{DIR_GROUP}\b", re.IGNORECASE),
    # INR 1,200.00 credited to A/c ... / Your A/c XX1234 credited Rs.500.00 ...
    re.compile(rf"{DIR_GROUP}\s+(?:with\s+|by\s+)?{AMT_GROUP}", re.IGNORECASE),
)


def parse(body: str) -> Parsed | None:
    return from_templates("bob", body, _TEMPLATES)
