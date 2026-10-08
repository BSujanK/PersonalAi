"""Balance-gap reconciliation. Some bank payments never produce an SMS, but the next SMS that
carries the available balance gives them away: the balance no longer follows from the previous
one. For each gap an *inferred* "unrecorded payment" row is kept so totals stay right.

``reconcile`` recomputes from scratch and is idempotent; it only changes inferred rows."""

from __future__ import annotations

import logging
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate, pairwise, permutations
from typing import cast

from agent.core.clock import Clock
from agent.finance.model import Bank, Direction, ParsedTxn
from agent.finance.store import FinanceStore, StoredTxn

log = logging.getLogger(__name__)

UNRECORDED = "unrecorded"
MIN_GAP_PAISE = 100  # smaller differences are rounding or a stale figure, not a payment
CLUSTER_SPAN = timedelta(minutes=5)  # two messages this close together can arrive out of order
MAX_PERMUTED = 4  # larger clusters keep their order: n! orderings would be too many
DEFAULT_LOOKBACK = timedelta(days=120)
DEFAULT_MAX_GAP_PAISE = 500_000


@dataclass(frozen=True)
class Mismatch:
    """A gap too large to be one unrecorded payment: shown to the owner, never turned into a row."""

    bank: str
    account_mask: str
    window_from: datetime
    window_to: datetime
    gap_paise: int


@dataclass(frozen=True)
class ReconcileResult:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    mismatches: tuple[Mismatch, ...] = ()


@dataclass(frozen=True)
class _Anchor:
    txn: StoredTxn
    balance: int  # available balance after this transaction


@dataclass(frozen=True)
class _Wanted:
    anchor: _Anchor  # the later reading of the pair
    window: tuple[datetime, datetime]
    direction: Direction
    amount_paise: int


def _signed(txn: StoredTxn) -> int:
    return txn.amount_paise if txn.direction == "credit" else -txn.amount_paise


class _Between:
    """Signed sum of the rows that carry no balance, by time."""

    def __init__(self, rows: list[StoredTxn]) -> None:
        ordered = sorted(rows, key=lambda t: t.occurred_at)
        self._times = [t.occurred_at for t in ordered]
        self._prefix = [0, *accumulate(_signed(t) for t in ordered)]

    def sum(self, low: datetime, high: datetime) -> int:
        """Rows strictly between ``low`` and ``high``."""
        first = bisect_right(self._times, low)
        last = bisect_left(self._times, high)
        return self._prefix[last] - self._prefix[first] if last > first else 0


def _gap(prev: _Anchor, cur: _Anchor, between: _Between) -> int:
    low, high = sorted((prev.txn.occurred_at, cur.txn.occurred_at))
    expected = prev.balance + between.sum(low, high) + _signed(cur.txn)
    return cur.balance - expected


def _clusters(anchors: list[_Anchor]) -> list[list[_Anchor]]:
    clusters: list[list[_Anchor]] = []
    for anchor in anchors:
        if clusters and anchor.txn.occurred_at - clusters[-1][-1].txn.occurred_at <= CLUSTER_SPAN:
            clusters[-1].append(anchor)
        else:
            clusters.append([anchor])
    return clusters


def _best_chain(anchors: list[_Anchor], between: _Between) -> list[_Anchor]:
    """Order the anchors by time, except that anchors close together are reordered so the chain
    has the smallest total gap. Ties keep the time order."""
    options: list[list[tuple[_Anchor, ...]]] = [
        list(permutations(c)) if len(c) <= MAX_PERMUTED else [tuple(c)] for c in _clusters(anchors)
    ]

    def inner(order: tuple[_Anchor, ...]) -> int:
        return sum(abs(_gap(a, b, between)) for a, b in pairwise(order))

    cost = [inner(o) for o in options[0]]
    back: list[list[int]] = []
    for before, here in pairwise(options):
        now: list[int] = []
        came: list[int] = []
        for order in here:
            best_cost, best_from = None, 0
            for j, earlier in enumerate(before):
                total = cost[j] + abs(_gap(earlier[-1], order[0], between))
                if best_cost is None or total < best_cost:
                    best_cost, best_from = total, j
            now.append((best_cost or 0) + inner(order))
            came.append(best_from)
        cost = now
        back.append(came)
    pick = min(range(len(cost)), key=lambda k: (cost[k], k))
    chain: list[tuple[_Anchor, ...]] = []
    for i in range(len(options) - 1, -1, -1):
        chain.append(options[i][pick])
        if i:
            pick = back[i - 1][pick]
    return [a for order in reversed(chain) for a in order]


def _plan(
    rows: list[StoredTxn], max_gap_paise: int
) -> tuple[dict[tuple[str, datetime, datetime, str], _Wanted], list[Mismatch]]:
    anchors_by_account: dict[str, list[_Anchor]] = defaultdict(list)
    loose: dict[str, list[StoredTxn]] = defaultdict(list)  # same-account rows with no balance
    account_less: list[StoredTxn] = []
    for txn in rows:
        if txn.inferred:
            continue
        if txn.account_hash is None:
            account_less.append(txn)
        elif txn.balance_paise is not None:
            anchors_by_account[txn.account_hash].append(_Anchor(txn, txn.balance_paise))
        else:
            loose[txn.account_hash].append(txn)
    single = len(anchors_by_account) == 1
    wanted: dict[tuple[str, datetime, datetime, str], _Wanted] = {}
    mismatches: list[Mismatch] = []
    for account_hash in sorted(anchors_by_account):
        anchors = anchors_by_account[account_hash]  # already in (occurred_at, id) order
        between = _Between([*loose[account_hash], *(account_less if single else [])])
        chain = _best_chain(anchors, between)
        for prev, cur in pairwise(chain):
            gap = _gap(prev, cur, between)
            if abs(gap) < MIN_GAP_PAISE:
                continue
            low, high = sorted((prev.txn.occurred_at, cur.txn.occurred_at))
            if abs(gap) > max_gap_paise:
                mismatches.append(
                    Mismatch(cur.txn.bank, cur.txn.account_mask or "", low, high, gap)
                )
                continue
            direction: Direction = "credit" if gap > 0 else "debit"
            wanted[(account_hash, low, high, direction)] = _Wanted(
                cur, (low, high), direction, abs(gap)
            )
    return wanted, mismatches


def reconcile(
    store: FinanceStore,
    now: datetime,
    *,
    lookback: timedelta = DEFAULT_LOOKBACK,
    max_gap_paise: int = DEFAULT_MAX_GAP_PAISE,
) -> ReconcileResult:
    """Bring the inferred rows in line with the balance gaps of the last ``lookback``.

    A gap that already has an inferred row (same account, window and direction) keeps that row,
    with its id and any category the owner set; only the amount follows the gap.
    """
    since = now - lookback
    with store.transaction():
        wanted, mismatches = _plan(store.txns_since(since), max_gap_paise)
        existing: dict[tuple[str, datetime, datetime, str], StoredTxn] = {}
        deleted = updated = inserted = 0
        for row in store.inferred_since(since):
            if row.account_hash is None or row.window_from is None or row.window_to is None:
                continue
            key = (row.account_hash, row.window_from, row.window_to, row.direction)
            if key in wanted and key not in existing:
                existing[key] = row
            else:
                store.delete_inferred(row.id)
                deleted += 1
        for key, want in wanted.items():
            kept = existing.get(key)
            if kept is None:
                anchor = want.anchor.txn
                low, high = want.window
                store.insert_inferred(
                    ParsedTxn(
                        bank=cast(Bank, anchor.bank),
                        account_mask=anchor.account_mask,
                        direction=want.direction,
                        amount_paise=want.amount_paise,
                        channel="other",
                        counterparty=None,
                        reference=None,
                        txn_date=None,
                        balance_paise=None,
                    ),
                    low + (high - low) / 2,
                    want.window,
                    (UNRECORDED, "rule"),
                )
                inserted += 1
            elif kept.amount_paise != want.amount_paise:
                store.set_inferred_amount(kept.id, want.amount_paise)
                updated += 1
    return ReconcileResult(inserted, updated, deleted, tuple(mismatches))


class Reconciler:
    """Runs ``reconcile`` on demand and remembers the latest mismatches for the API."""

    def __init__(self, store: FinanceStore, clock: Clock, max_gap_paise: int) -> None:
        self._store = store
        self._clock = clock
        self._max_gap_paise = max_gap_paise
        self._mismatches: tuple[Mismatch, ...] = ()

    @property
    def mismatches(self) -> tuple[Mismatch, ...]:
        return self._mismatches

    def run(self) -> None:
        """Never raises: a failed run keeps the previous mismatches and logs the error type."""
        try:
            result = reconcile(self._store, self._clock(), max_gap_paise=self._max_gap_paise)
        except Exception as exc:
            log.warning("finance reconcile failed: %s", type(exc).__name__)
            return
        self._mismatches = result.mismatches
        if result.inserted or result.updated or result.deleted:
            log.info(
                "finance reconcile: inserted=%d updated=%d deleted=%d",
                result.inserted,
                result.updated,
                result.deleted,
            )
