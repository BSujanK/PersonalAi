from __future__ import annotations

import json
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from agent.connectors.drive import DriveFileNotFound
from agent.connectors.drive_google import GoogleDriveApi, build_drive_api
from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    DRIVE_FILE,
    DRIVE_READONLY,
    GoogleAuth,
    GoogleNotConfigured,
    token_secret_name,
)
from agent.store.keystore import KeyStore

ACCOUNT = "me@example.com"


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


class _Files:
    def __init__(self, request: _Request) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._request = request

    def __getattr__(self, name: str) -> Any:
        def method(**kwargs: Any) -> _Request:
            self.calls.append((name, kwargs))
            return self._request

        return method


class _Service:
    def __init__(self, request: _Request) -> None:
        self.files_resource = _Files(request)

    def files(self) -> _Files:
        return self.files_resource


def _api(result: Any = None, status: int | None = None) -> tuple[GoogleDriveApi, _Files]:
    service = _Service(_Request(result, status))
    return GoogleDriveApi(service), service.files_resource


def test_search_always_excludes_trashed_and_limits_fields() -> None:
    api, files = _api({"files": [{"id": "a"}]})
    assert api.search(None, 5) == [{"id": "a"}]
    _, kwargs = files.calls[0]
    assert kwargs["q"] == "trashed = false"
    assert kwargs["pageSize"] == 5
    assert "owners" not in kwargs["fields"]
    assert "permissions" not in kwargs["fields"]
    assert kwargs["fields"] == "files(id,name,mimeType,modifiedTime,size)"


def test_query_is_escaped_against_injection() -> None:
    api, files = _api({"files": []})
    api.search("x' or name contains '", 5)
    q = files.calls[0][1]["q"]
    assert q == "trashed = false and fullText contains 'x\\' or name contains \\''"
    api.search("back\\slash", 5)
    assert files.calls[1][1]["q"].endswith("contains 'back\\\\slash'")


def test_404_maps_to_not_found_and_other_errors_propagate() -> None:
    with pytest.raises(DriveFileNotFound):
        _api(status=404)[0].get_metadata("f")
    with pytest.raises(HttpError):
        _api(status=500)[0].get_metadata("f")


def test_download_refuses_large_files_before_fetching() -> None:
    api, files = _api({"size": "100"})
    with pytest.raises(ValueError):
        api.download("f", 50)
    assert [name for name, _ in files.calls] == ["get"]


def test_download_and_export_return_bytes() -> None:
    assert _api(b"abc")[0].export("f", "text/plain") == b"abc"


def test_create_file_sends_private_body_only() -> None:
    api, files = _api({"id": "new"})
    assert api.create_file("n.txt", "text/plain", b"hi") == {"id": "new"}
    name, kwargs = files.calls[0]
    assert name == "create"
    assert kwargs["body"] == {"name": "n.txt", "mimeType": "text/plain"}


def test_after_call_hook_runs() -> None:
    hits: list[int] = []
    GoogleDriveApi(_Service(_Request({"files": []})), lambda: hits.append(1)).search(None, 1)
    assert hits == [1]


def _keystore(scopes: list[str]) -> KeyStore:
    keystore = KeyStore()
    keystore.set(
        CLIENT_SECRET_NAME,
        json.dumps({"installed": {"client_id": "cid", "client_secret": "csec"}}),
    )
    keystore.set(
        token_secret_name(ACCOUNT),
        json.dumps({"refresh_token": "rt", "token": "at", "scopes": scopes}),
    )
    return keystore


def test_build_requires_drive_scopes() -> None:
    with pytest.raises(GoogleNotConfigured):
        build_drive_api(ACCOUNT, GoogleAuth(_keystore([DRIVE_READONLY])))


def test_build_with_both_scopes() -> None:
    api = build_drive_api(ACCOUNT, GoogleAuth(_keystore([DRIVE_READONLY, DRIVE_FILE])))
    assert isinstance(api, GoogleDriveApi)


def test_module_has_no_share_delete_or_update_calls() -> None:
    from pathlib import Path

    import agent.connectors.drive_google as module

    source = Path(module.__file__).read_text()
    for forbidden in ("permissions", ".delete(", ".update(", ".copy(", "emptyTrash"):
        assert forbidden not in source
