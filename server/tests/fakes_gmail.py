"""In-memory Gmail API implementing ``GmailApi``. Synthetic data only."""

from __future__ import annotations

import base64
from typing import Any

from agent.connectors.gmail import HistoryExpired, MessageNotFound


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def make_resource(
    message_id: str,
    *,
    from_: str = "Alice Example <alice@example.com>",
    to: str = "me@example.com",
    cc: str | None = None,
    subject: str = "Hello",
    body: str = "Plain body",
    html: str | None = None,
    labels: tuple[str, ...] = ("INBOX", "UNREAD"),
    internal_date: int = 1_790_000_000_000,
    thread_id: str | None = None,
    history_id: str = "1",
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = [
        {"name": "From", "value": from_},
        {"name": "To", "value": to},
        {"name": "Subject", "value": subject},
    ]
    if cc:
        headers.append({"name": "Cc", "value": cc})
    headers += [{"name": k, "value": v} for k, v in (extra_headers or {}).items()]
    parts: list[dict[str, Any]] = [
        {"mimeType": "text/plain", "body": {"data": b64(body)}},
    ]
    if html is not None:
        parts.append({"mimeType": "text/html", "body": {"data": b64(html)}})
    return {
        "id": message_id,
        "threadId": thread_id or f"t-{message_id}",
        "historyId": history_id,
        "internalDate": str(internal_date),
        "labelIds": list(labels),
        "snippet": body[:60],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": headers,
            "parts": parts,
        },
    }


class FakeGmailApi:
    """Mailbox with a history log, pagination, history expiry and recorded writes."""

    def __init__(self, address: str = "me@example.com", page_size: int = 2) -> None:
        self.address = address
        self.page_size = page_size
        self.messages: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.history_id = 1000
        self.expired_before = 0  # list_history raises when start < expired_before
        self.get_calls: list[str] = []
        self.list_queries: list[str] = []
        self.batch_modify_calls: list[tuple[list[str], list[str], list[str]]] = []
        self.trash_calls: list[str] = []

    # --- test-side mutation ---------------------------------------------------------------

    def _record(self, **kinds: list[dict[str, Any]]) -> None:
        self.history_id += 1
        self.history.append({"id": str(self.history_id), **kinds})

    def _stub(self, message_id: str) -> dict[str, Any]:
        res = self.messages[message_id]
        return {"id": message_id, "threadId": res["threadId"], "labelIds": list(res["labelIds"])}

    def add_message(self, message_id: str, **kwargs: Any) -> dict[str, Any]:
        self.history_id += 1
        resource = make_resource(message_id, history_id=str(self.history_id), **kwargs)
        self.messages[message_id] = resource
        self.history.append(
            {"id": str(self.history_id), "messagesAdded": [{"message": self._stub(message_id)}]}
        )
        return resource

    def add_label(self, message_id: str, label: str) -> None:
        labels = self.messages[message_id]["labelIds"]
        if label not in labels:
            labels.append(label)
        self._record(labelsAdded=[{"message": self._stub(message_id), "labelIds": [label]}])

    def remove_label(self, message_id: str, label: str) -> None:
        labels = self.messages[message_id]["labelIds"]
        if label in labels:
            labels.remove(label)
        self._record(labelsRemoved=[{"message": self._stub(message_id), "labelIds": [label]}])

    def delete_message(self, message_id: str) -> None:
        stub = self._stub(message_id)
        del self.messages[message_id]
        self._record(messagesDeleted=[{"message": stub}])

    def expire_history(self) -> None:
        """Make every currently issued history id stale."""
        self.expired_before = self.history_id + 1

    # --- GmailApi -------------------------------------------------------------------------

    def profile(self) -> dict[str, Any]:
        return {"emailAddress": self.address, "historyId": str(self.history_id)}

    def list_message_ids(self, query: str, page_token: str | None) -> tuple[list[str], str | None]:
        self.list_queries.append(query)
        ids = sorted(self.messages)
        start = int(page_token or 0)
        end = start + self.page_size
        return ids[start:end], (str(end) if end < len(ids) else None)

    def get_message(self, message_id: str) -> dict[str, Any]:
        self.get_calls.append(message_id)
        if message_id not in self.messages:
            raise MessageNotFound(message_id)
        return self.messages[message_id]

    def list_history(
        self, start_history_id: str, page_token: str | None
    ) -> tuple[list[dict[str, Any]], str, str | None]:
        if int(start_history_id) < self.expired_before:
            raise HistoryExpired(start_history_id)
        pending = [r for r in self.history if int(r["id"]) > int(start_history_id)]
        start = int(page_token or 0)
        end = start + self.page_size
        return pending[start:end], str(self.history_id), (str(end) if end < len(pending) else None)

    def batch_modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        assert len(ids) <= 1000
        self.batch_modify_calls.append((list(ids), list(add), list(remove)))
        for message_id in ids:
            for label in add:
                self.add_label(message_id, label)
            for label in remove:
                self.remove_label(message_id, label)

    def trash(self, message_id: str) -> None:
        self.trash_calls.append(message_id)
        self.add_label(message_id, "TRASH")
        self.remove_label(message_id, "INBOX")
