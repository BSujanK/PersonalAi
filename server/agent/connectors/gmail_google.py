"""``GmailApi`` over google-api-python-client. Credentials live only in the OS keyring."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.connectors.gmail import MAX_BATCH_IDS, HistoryExpired, MessageNotFound
from agent.store.keystore import KeyStore

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"  # no send scope in M2
CLIENT_SECRET_NAME = "google_oauth_client"  # noqa: S105 - keyring entry name
_HISTORY_TYPES = ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"]
_RETRIES = 3


class GmailNotConfigured(RuntimeError):
    """The OAuth client or the account's token is missing from the keyring."""


def token_secret_name(account: str) -> str:
    return f"google_oauth:{account}"


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


def _client_config(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    inner = data.get("installed") or data.get("web") or data
    config: dict[str, Any] = inner
    return config


def build_gmail_api(account: str, keystore: KeyStore) -> GoogleGmailApi:
    client_raw = keystore.get(CLIENT_SECRET_NAME)
    token_raw = keystore.get(token_secret_name(account))
    if client_raw is None or token_raw is None:
        raise GmailNotConfigured("google oauth client or account token missing from keyring")
    client = _client_config(client_raw)
    info: dict[str, Any] = json.loads(token_raw)
    info.setdefault("client_id", client.get("client_id"))
    info.setdefault("client_secret", client.get("client_secret"))
    info.setdefault("token_uri", client.get("token_uri", "https://oauth2.googleapis.com/token"))
    credentials = Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
        info, scopes=[GMAIL_SCOPE]
    )
    saved = {"token": credentials.token}

    def persist_refreshed() -> None:
        if credentials.token != saved["token"]:
            keystore.set(token_secret_name(account), credentials.to_json())
            saved["token"] = credentials.token

    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    return GoogleGmailApi(service, persist_refreshed)
