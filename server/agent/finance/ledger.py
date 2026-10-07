"""The transaction ledger: dedup across SMS and email, rule categorisation and balances."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from agent.core.clock import Clock
from agent.finance.model import ParsedBalance, ParsedTxn
from agent.finance.store import CategorySource, FinanceStore, Source, StoredTxn

DEDUP_WINDOW = timedelta(hours=2)

Rules = Callable[[str | None, str, str, str | None], tuple[str, CategorySource] | None]


class Ledger:
    def __init__(self, store: FinanceStore, rules: Rules, clock: Clock) -> None:
        self._store = store
        self._rules = rules
        self._clock = clock

    def record(self, parsed: ParsedTxn, occurred_at: datetime, source: Source) -> tuple[int, bool]:
        """Store a transaction, or merge it into the same payment seen via the other source.

        Returns ``(txn_id, merged)``. A row with the same bank reference is the same payment,
        whatever its source. Without a shared reference, rows from the same source are never
        merged, so two genuine identical payments stay two rows.
        """
        with self._store.transaction():
            match = (
                self._store.find_by_reference(parsed.bank, parsed.direction, parsed.reference)
                if parsed.reference
                else None
            ) or self._find_match(parsed, occurred_at, source)
            if match is not None:
                self._store.merge_txn(match.id, parsed, source, match)
                self._categorize_if_missing(match.id)
                txn_id, merged = match.id, True
            else:
                txn_id = self._store.insert_txn(
                    parsed, occurred_at, source, self._categorize(parsed)
                )
                merged = False
            if parsed.balance_paise is not None and parsed.account_mask:
                self._store.upsert_balance(
                    parsed.bank, parsed.account_mask, parsed.balance_paise, occurred_at, source
                )
        return txn_id, merged

    def record_balance(self, parsed: ParsedBalance, as_of: datetime, source: Source) -> bool:
        """Store a balance-only message. True when it replaced an older figure."""
        return self._store.upsert_balance(
            parsed.bank, parsed.account_mask, parsed.balance_paise, as_of, source
        )

    def _find_match(
        self, parsed: ParsedTxn, occurred_at: datetime, source: Source
    ) -> StoredTxn | None:
        candidates = self._store.find_dedup_candidates(
            parsed.direction, occurred_at, DEDUP_WINDOW, parsed.reference, source
        )
        account_hash = (
            self._store.account_hash(parsed.bank, parsed.account_mask)
            if parsed.account_mask
            else None
        )
        reference_hash = self._store.reference_hash(parsed.reference) if parsed.reference else None
        eligible: list[StoredTxn] = []
        for txn in candidates:
            if reference_hash is not None and txn.reference_hash == reference_hash:
                eligible.append(txn)
                continue
            if reference_hash is not None and txn.reference_hash is not None:
                continue  # both carry a reference and they differ: different payments
            within = abs(txn.occurred_at - occurred_at) <= DEDUP_WINDOW
            same_account = (
                account_hash is None or txn.account_hash is None or txn.account_hash == account_hash
            )
            if within and same_account and txn.amount_paise == parsed.amount_paise:
                eligible.append(txn)
        if not eligible:
            return None
        return min(eligible, key=lambda t: (abs(t.occurred_at - occurred_at), t.id))

    def _categorize(self, parsed: ParsedTxn) -> tuple[str, CategorySource] | None:
        owner = self._store.category_rule(parsed.counterparty) if parsed.counterparty else None
        return self._rules(parsed.counterparty, parsed.direction, parsed.channel, owner)

    def _categorize_if_missing(self, txn_id: int) -> None:
        txn = self._store.get_txn(txn_id)
        if txn is None or txn.category is not None:
            return
        owner = self._store.category_rule(txn.counterparty) if txn.counterparty else None
        decided = self._rules(txn.counterparty, txn.direction, txn.channel, owner)
        if decided is not None:
            self._store.set_category(txn_id, *decided)
