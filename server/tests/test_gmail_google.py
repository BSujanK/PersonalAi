from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from agent.connectors.gmail import HistoryExpired, MessageNotFound
from agent.connectors.gmail_google import GoogleGmailApi, build_gmail_api
from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    GMAIL_MODIFY,
    GoogleAuth,
    GoogleNotConfigured,
    token_secret_name,
)
from agent.store.keystore import KeyStore


class _Resp:
    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "x"


class _Request:
    def __init__(self, result: Any = None, status: int | None = None) -> None:
        self._result = result
        self._status = status

    def execute(self, num_retries: int = 0) -> Any:
        if self._status is not None:
            raise HttpError(_Resp(self._status), b"{}")  # type: ignore[no-untyped-call]
        return self._result


class _Resource:
    """Records calls; every method returns the configured request."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]], request: _Request) -> None:
        self._calls = calls
        self._request = request

    def __getattr__(self, name: str) -> Any:
        def method(**kwargs: Any) -> _Request:
            self._calls.append((name, kwargs))
            return self._request

        return method


class _Service:
    def __init__(self, request: _Request) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._res = _Resource(self.calls, request)

    def users(self) -> _Service:
        return self

    def messages(self) -> _Resource:
        return self._res

    def history(self) -> _Resource:
        return self._res

    def getProfile(self, **kw: Any) -> _Request:
        self.calls.append(("getProfile", kw))
        return self._res._request


def test_history_404_maps_to_history_expired() -> None:
    api = GoogleGmailApi(_Service(_Request(status=404)))
    with pytest.raises(HistoryExpired):
        api.list_history("5", None)


def test_message_404_maps_to_not_found_and_other_errors_propagate() -> None:
    with pytest.raises(MessageNotFound):
        GoogleGmailApi(_Service(_Request(status=404))).get_message("m")
    with pytest.raises(HttpError):
        GoogleGmailApi(_Service(_Request(status=500))).get_message("m")
    with pytest.raises(HttpError):
        GoogleGmailApi(_Service(_Request(status=403))).list_history("5", None)


def test_requests_are_shaped_as_specified() -> None:
    service = _Service(
        _Request(
            {
                "history": [{"id": "6"}],
                "historyId": "9",
                "nextPageToken": "n",
                "messages": [{"id": "a"}],
            }
        )
    )
    api = GoogleGmailApi(service)
    assert api.list_history("5", "tok") == ([{"id": "6"}], "9", "n")
    assert api.list_message_ids("newer_than:7d", None) == (["a"], "n")
    api.batch_modify(["a", "b"], ["STARRED"], ["INBOX"])
    api.trash("a")
    api.profile()
    by_name = {name: kwargs for name, kwargs in service.calls}
    assert by_name["list"]["userId"] == "me"
    assert set(by_name["list"]) >= {"q", "pageToken"}
    assert by_name["batchModify"]["body"] == {
        "ids": ["a", "b"],
        "addLabelIds": ["STARRED"],
        "removeLabelIds": ["INBOX"],
    }
    assert by_name["trash"] == {"userId": "me", "id": "a"}
    with pytest.raises(ValueError):
        api.batch_modify(["x"] * 1001, [], ["INBOX"])


def test_history_types_requested() -> None:
    service = _Service(_Request({"historyId": "9"}))
    GoogleGmailApi(service).list_history("5", None)
    types = next(kw for _, kw in service.calls if "historyTypes" in kw)["historyTypes"]
    assert set(types) == {"messageAdded", "messageDeleted", "labelAdded", "labelRemoved"}


def test_after_call_hook_runs() -> None:
    hits: list[int] = []
    GoogleGmailApi(_Service(_Request({})), lambda: hits.append(1)).profile()
    assert hits == [1]


def test_build_requires_secrets() -> None:
    with pytest.raises(GoogleNotConfigured):
        build_gmail_api("me@example.com", GoogleAuth(KeyStore()))


def test_build_uses_shared_credential_from_keyring() -> None:
    keystore = KeyStore()
    keystore.set(
        CLIENT_SECRET_NAME,
        json.dumps({"installed": {"client_id": "cid", "client_secret": "csec"}}),
    )
    keystore.set(
        token_secret_name("me@example.com"),
        json.dumps({"refresh_token": "rt", "token": "at", "scopes": [GMAIL_MODIFY]}),
    )
    api = build_gmail_api("me@example.com", GoogleAuth(keystore))
    credentials = api._service._http.credentials
    assert list(credentials.scopes) == [GMAIL_MODIFY]
    assert credentials.client_id == "cid"
    assert credentials.refresh_token == "rt"


def test_no_code_calls_a_gmail_send_endpoint() -> None:
    agent_dir = Path(__file__).resolve().parent.parent / "agent"
    endpoint = re.compile(r"\b(messages|drafts)\(\)\s*\.\s*send\b")
    method = re.compile(r"""["']send["']""")
    offenders = [
        str(path.relative_to(agent_dir))
        for path in agent_dir.rglob("*.py")
        if endpoint.search(text := path.read_text()) or method.search(text)
    ]
    assert offenders == []
