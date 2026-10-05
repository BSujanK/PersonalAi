"""Wiring for the finance feature, shared by the entry point and tests."""

from __future__ import annotations

from dataclasses import dataclass

from agent.config import Settings
from agent.core.clock import Clock
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.finance.categorize import FinanceCategorizer, categorize_by_rules
from agent.finance.email_alerts import parse_alert_email
from agent.finance.ingest import FinanceIngest
from agent.finance.ledger import Ledger
from agent.finance.sms_parsers import bank_for_sender, parse_sms
from agent.finance.store import FinanceStore
from agent.finance.tools import register_finance_tools
from agent.mail.classify import build_classifier_llm
from agent.store.crypto import FieldCipher
from agent.store.db import Database

MAX_OFFSET_MINUTES = 14 * 60


@dataclass(frozen=True)
class FinanceServices:
    store: FinanceStore
    ledger: Ledger
    ingest: FinanceIngest
    categorizer: FinanceCategorizer


def setup_finance(
    settings: Settings, db: Database, db_key: bytes, registry: ToolRegistry, clock: Clock
) -> FinanceServices:
    """Register the finance tools and build the services. Raises ``ValueError`` on bad config."""
    offset = settings.finance_utc_offset_minutes
    if abs(offset) > MAX_OFFSET_MINUTES:
        raise ValueError("PERSONALAI_FINANCE_UTC_OFFSET_MINUTES must be within 14 hours of UTC")
    if settings.finance_categorize_minutes < 1:
        raise ValueError("PERSONALAI_FINANCE_CATEGORIZE_MINUTES must be at least 1")
    store = FinanceStore(db, FieldCipher(db_key), db_key, clock)
    ledger = Ledger(store, categorize_by_rules, clock)
    ingest = FinanceIngest(store, ledger, parse_sms, bank_for_sender, parse_alert_email)
    categorizer = FinanceCategorizer(
        store, build_classifier_llm(settings), Redactor(settings.redaction_emails)
    )
    register_finance_tools(registry, store, clock, offset)
    return FinanceServices(store, ledger, ingest, categorizer)
