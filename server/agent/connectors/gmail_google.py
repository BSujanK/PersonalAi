"""``GmailApi`` over google-api-python-client. Credentials live only in the OS keyring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.connectors.gmail import MAX_BATCH_IDS, HistoryExpired, MessageNotFound
from agent.connectors.google_auth import GMAIL_MODIFY, GoogleAuth

# gmail.modify covers read, label, archive, trash and send. Sending happens only in ``send``,
# which only the executors of the approval-gated mail_send and mail_reply tools call
# (tests/test_gmail_google.py checks that no other module reaches it).
_HISTORY_TYPES = ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"]
_RETRIES = 3


def _status(exc: HttpError) -> int | None:
    status = getattr(exc.resp, "status", None)
    return int(status) if status is not None else None


class GoogleGmailApi:
    def __init__(self, service: Any, after_call: Callable[[], None] | None = None) -> None:
        self._service = service
        self._after_call = after_call

    def _execute(self, request: Any) -> Any:
        result = request.execute(num_retries=_RETRIES)
        if self._after_call is not None:
            self._after_call()
        return result

    def profile(self) -> dict[str, Any]:
        result: dict[str, Any] = self._execute(self._service.users().getProfile(userId="me"))
        return result

    def list_message_ids(self, query: str, page_token: str | None) -> tuple[list[str], str | None]:
        result = self._execute(
            self._service.users()
            .messages()
            .list(userId="me", q=query, pageToken=page_token, maxResults=500)
        )
        ids = [m["id"] for m in result.get("messages", [])]
        return ids, result.get("nextPageToken")

    def get_message(self, message_id: str) -> dict[str, Any]:
        try:
            result: dict[str, Any] = self._execute(
                self._service.users().messages().get(userId="me", id=message_id, format="full")
            )
        except HttpError as exc:
            if _status(exc) == 404:
                raise MessageNotFound(message_id) from None
            raise
        return result

    def list_history(
        self, start_history_id: str, page_token: str | None
    ) -> tuple[list[dict[str, Any]], str, str | None]:
        try:
            result = self._execute(
                self._service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=_HISTORY_TYPES,
                    pageToken=page_token,
                )
            )
        except HttpError as exc:
            if _status(exc) == 404:
                raise HistoryExpired(start_history_id) from None
            raise
        return result.get("history", []), str(result["historyId"]), result.get("nextPageToken")

    def batch_modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        if len(ids) > MAX_BATCH_IDS:
            raise ValueError("batch_modify accepts at most 1000 ids")
        self._execute(
            self._service.users()
            .messages()
            .batchModify(
                userId="me", body={"ids": ids, "addLabelIds": add, "removeLabelIds": remove}
            )
        )

    def trash(self, message_id: str) -> None:
        self._execute(self._service.users().messages().trash(userId="me", id=message_id))

    def send(self, raw: str, thread_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        # No automatic retries: a retried send after a lost response could deliver twice.
        result: dict[str, Any] = (
            self._service.users().messages().send(userId="me", body=body).execute()
        )
        if self._after_call is not None:
            self._after_call()
        return result


def build_gmail_api(account: str, auth: GoogleAuth) -> GoogleGmailApi:
    credentials = auth.credentials(account, [GMAIL_MODIFY])
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    return GoogleGmailApi(service, auth.persist_hook(account))
