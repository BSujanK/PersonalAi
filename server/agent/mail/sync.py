"""Gmail -> local store synchronisation (full and incremental). Logs ids and counts only."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from agent.connectors.gmail import (
    GmailApi,
    HistoryExpired,
    MailMessage,
    MalformedMessage,
    MessageNotFound,
    parse_message,
)
from agent.core.clock import Clock
from agent.mail.store import MailStore

log = logging.getLogger(__name__)

MAX_FULL_SYNC_IDS = 2000


class MessageClassifier(Protocol):
    def classify(self, msg: MailMessage) -> object: ...


@dataclass(frozen=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    full: bool = False


@dataclass
class _Counts:
    added: int = 0
    updated: int = 0
    deleted: int = 0


def _history_messages(record: dict[str, Any], key: str) -> Iterable[dict[str, Any]]:
    for entry in record.get(key) or []:
        message = entry.get("message") if isinstance(entry, dict) else None
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            yield entry


class MailSync:
    def __init__(
        self,
        store: MailStore,
        api_for: Callable[[str], GmailApi],
        classifier: MessageClassifier | None,
        clock: Clock,
        initial_days: int,
    ) -> None:
        self._store = store
        self._api_for = api_for
        self._classifier = classifier
        self._clock = clock
        self._initial_days = initial_days

    def sync_all(self, accounts: Iterable[str]) -> dict[str, SyncStats | str]:
        """Sync each account; a failure is recorded as the exception's type name."""
        results: dict[str, SyncStats | str] = {}
        for index, account in enumerate(accounts):
            try:
                results[account] = self.sync_account(account)
            except Exception as exc:
                log.warning("mail sync failed for account #%d: %s", index, type(exc).__name__)
                results[account] = type(exc).__name__
        return results

    def sync_account(self, account: str) -> SyncStats:
        api = self._api_for(account)
        start = self._store.get_history_id(account)
        if start is None:
            return self._full_sync(account, api)
        try:
            return self._incremental(account, api, start)
        except HistoryExpired:
            log.info("mail history expired; running a full sync")
            return self._full_sync(account, api)

    # --- internals ------------------------------------------------------------------------

    def _full_sync(self, account: str, api: GmailApi) -> SyncStats:
        # Read the cursor before listing so mail arriving during the listing is replayed later.
        history_id = str(api.profile()["historyId"])
        ids: list[str] = []
        token: str | None = None
        while len(ids) < MAX_FULL_SYNC_IDS:
            page, token = api.list_message_ids(f"newer_than:{self._initial_days}d", token)
            ids.extend(page)
            if token is None:
                break
        counts = _Counts()
        for message_id in ids[:MAX_FULL_SYNC_IDS]:
            self._fetch_and_store(account, api, message_id, counts)
        self._store.set_history_id(account, history_id, self._clock().isoformat())
        log.info("mail full sync: added=%d updated=%d", counts.added, counts.updated)
        return SyncStats(counts.added, counts.updated, 0, True)

    def _incremental(self, account: str, api: GmailApi, start: str) -> SyncStats:
        added: dict[str, None] = {}  # ordered set of ids to fetch
        deleted: dict[str, None] = {}
        label_ops: list[tuple[str, dict[str, Any], str]] = []  # (id, record entry, kind)
        latest = start
        token: str | None = None
        while True:
            records, latest, token = api.list_history(start, token)
            for record in records:
                for entry in _history_messages(record, "messagesAdded"):
                    added[entry["message"]["id"]] = None
                for entry in _history_messages(record, "messagesDeleted"):
                    deleted[entry["message"]["id"]] = None
                for key in ("labelsAdded", "labelsRemoved"):
                    for entry in _history_messages(record, key):
                        label_ops.append((entry["message"]["id"], entry, key))
            if token is None:
                break
        counts = _Counts()
        for message_id in added:
            if message_id not in deleted:
                self._fetch_and_store(account, api, message_id, counts)
        for message_id, entry, kind in label_ops:
            if message_id not in added and message_id not in deleted:
                self._apply_label_change(account, message_id, entry, kind, counts)
        for message_id in deleted:
            if self._store.mark_deleted(account, message_id):
                counts.deleted += 1
        self._store.set_history_id(account, latest, self._clock().isoformat())
        log.info(
            "mail incremental sync: added=%d updated=%d deleted=%d",
            counts.added,
            counts.updated,
            counts.deleted,
        )
        return SyncStats(counts.added, counts.updated, counts.deleted, False)

    def _fetch_and_store(
        self, account: str, api: GmailApi, message_id: str, counts: _Counts
    ) -> None:
        try:
            msg = parse_message(account, api.get_message(message_id))
        except MessageNotFound:
            return
        except MalformedMessage:
            log.warning("skipping malformed message %s", message_id)
            return
        is_new = self._store.upsert(msg)
        if "SENT" in msg.label_ids:
            self._store.add_replied(account, msg.to)
        if is_new:
            counts.added += 1
            self._classify(msg)
        else:
            counts.updated += 1

    def _classify(self, msg: MailMessage) -> None:
        if self._classifier is None:
            return
        try:
            self._classifier.classify(msg)
        except Exception as exc:
            log.warning("classification failed for %s: %s", msg.id, type(exc).__name__)

    def _apply_label_change(
        self, account: str, message_id: str, entry: dict[str, Any], kind: str, counts: _Counts
    ) -> None:
        current = self._store.get_labels(account, message_id)
        if current is None:
            return
        known = entry["message"].get("labelIds")
        delta = [str(x) for x in entry.get("labelIds") or []]
        if isinstance(known, list):
            labels = [str(x) for x in known]
        elif kind == "labelsAdded":
            labels = [*current, *(x for x in delta if x not in current)]
        else:
            labels = [x for x in current if x not in delta]
        if self._store.update_labels(account, message_id, labels):
            counts.updated += 1
