from __future__ import annotations

from typing import Any

import pytest

from agent.connectors.drive import DriveFileNotFound
from agent.core.tools import ToolKind, ToolRegistry
from agent.workspace.drive_tools import MAX_DOWNLOAD_BYTES, register_drive_tools
from tests.support import DEVICE_ID, make_env, request_for

ACCOUNT = "me@example.com"
OTHER = "college@example.com"
DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
SLIDES = "application/vnd.google-apps.presentation"


class FakeDrive:
    def __init__(self) -> None:
        self.meta: dict[str, dict[str, Any]] = {}
        self.exported: dict[str, bytes] = {}
        self.blobs: dict[str, bytes] = {}
        self.export_calls: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str | None, int]] = []
        self.created: list[tuple[str, str, bytes]] = []
        self.parents: list[str | None] = []
        self.shared: list[tuple[str, dict[str, Any], bool]] = []

    def search(self, query: str | None, limit: int) -> list[dict[str, Any]]:
        self.search_calls.append((query, limit))
        return [
            {
                "id": "f1",
                "name": "Notes",
                "mimeType": "text/plain",
                "modifiedTime": "2026-10-01T00:00:00Z",
                "size": "5",
            }
        ]

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        if file_id not in self.meta:
            raise DriveFileNotFound
        return self.meta[file_id]

    def export(self, file_id: str, mime: str) -> bytes:
        self.export_calls.append((file_id, mime))
        return self.exported[file_id]

    def download(self, file_id: str, max_bytes: int) -> bytes:
        data = self.blobs[file_id]
        if len(data) > max_bytes:
            raise ValueError("too big")
        return data

    def create_file(
        self, name: str, mime: str, content: bytes, parent: str | None = None
    ) -> dict[str, Any]:
        self.created.append((name, mime, content))
        self.parents.append(parent)
        return {"id": "created1", "name": name, "webViewLink": "https://drive.example.com/c1"}

    def share(self, file_id: str, permission: dict[str, Any], notify: bool) -> dict[str, Any]:
        self.shared.append((file_id, dict(permission), notify))
        return {"id": f"perm{len(self.shared)}"}


def _setup() -> tuple[ToolRegistry, FakeDrive]:
    registry = ToolRegistry()
    drive = FakeDrive()
    register_drive_tools(registry, lambda _account: drive, [ACCOUNT, OTHER])
    return registry, drive


def _run(registry: ToolRegistry, name: str, args: dict[str, Any]) -> Any:
    tool = registry.get(name)
    assert tool is not None
    return tool.run(args)


def test_kinds() -> None:
    registry, _ = _setup()
    assert registry.kind_of("drive_search") is ToolKind.READ
    assert registry.kind_of("drive_read") is ToolKind.READ
    assert registry.kind_of("drive_create_text_file") is ToolKind.WRITE
    names = {s["function"]["name"] for s in registry.schemas()}
    assert names == {"drive_search", "drive_read", "drive_create_text_file"}


def test_search_all_accounts_and_validation() -> None:
    registry, drive = _setup()
    result = _run(registry, "drive_search", {"query": "plan", "limit": 3})
    assert result[0]["account"] == ACCOUNT
    assert set(result[0]) == {"account", "id", "name", "mime", "modified", "size"}
    assert len(drive.search_calls) == 2
    for bad in ({"limit": 0}, {"limit": 21}, {"query": "x" * 101}, {"account": "evil@example.com"}):
        with pytest.raises(ValueError):
            _run(registry, "drive_search", bad)


@pytest.mark.parametrize(
    ("mime", "expected"), [(DOC, "text/plain"), (SHEET, "text/csv"), (SLIDES, "text/plain")]
)
def test_read_exports_google_native_files(mime: str, expected: str) -> None:
    registry, drive = _setup()
    drive.meta["f1"] = {"name": "Thing", "mimeType": mime}
    drive.exported["f1"] = b"exported text"
    result = _run(registry, "drive_read", {"account": ACCOUNT, "file_id": "f1"})
    assert drive.export_calls == [("f1", expected)]
    assert result == {
        "account": ACCOUNT,
        "id": "f1",
        "name": "Thing",
        "text": "exported text",
        "truncated": False,
    }


def test_read_downloads_supported_and_truncates() -> None:
    registry, drive = _setup()
    drive.meta["f2"] = {"name": "log.TXT", "mimeType": "text/plain"}
    drive.blobs["f2"] = b"y" * 9000
    result = _run(registry, "drive_read", {"account": ACCOUNT, "file_id": "f2"})
    assert len(result["text"]) == 8000
    assert result["truncated"] is True


def test_read_refuses_unsupported_large_missing_and_bad_ids() -> None:
    registry, drive = _setup()
    drive.meta["f3"] = {"name": "photo.png", "mimeType": "image/png"}
    assert _run(registry, "drive_read", {"account": ACCOUNT, "file_id": "f3"}) == {
        "error": "unsupported file type"
    }
    drive.meta["f4"] = {"name": "big.txt", "mimeType": "text/plain"}
    drive.blobs["f4"] = b"z" * (MAX_DOWNLOAD_BYTES + 1)
    assert "error" in _run(registry, "drive_read", {"account": ACCOUNT, "file_id": "f4"})
    assert "error" in _run(registry, "drive_read", {"account": ACCOUNT, "file_id": "nope"})
    for bad in ("a/b", "", "x" * 129, "id' or 1"):
        with pytest.raises(ValueError):
            _run(registry, "drive_read", {"account": ACCOUNT, "file_id": bad})


def test_create_validation() -> None:
    registry, _ = _setup()
    tool = registry.get("drive_create_text_file")
    assert tool is not None and tool.preview is not None
    good = {"account": ACCOUNT, "name": "n.txt", "content": "hi"}
    tool.preview(good)
    bad_args: list[dict[str, Any]] = [
        {**good, "name": ""},
        {**good, "name": "a/b"},
        {**good, "name": "a\\b"},
        {**good, "name": "a\nb"},
        {**good, "name": "n" * 201},
        {**good, "content": "c" * 20_001},
        {**good, "mime": "application/pdf"},
        {**good, "account": "evil@example.com"},
    ]
    for bad in bad_args:
        with pytest.raises(ValueError):
            tool.preview(bad)
        with pytest.raises(ValueError):
            tool.run(bad)


def test_create_runs_only_through_approval() -> None:
    env = make_env()
    drive = FakeDrive()
    register_drive_tools(env.registry, lambda _account: drive, [ACCOUNT])
    content = "line one\nline two with a distinctive tail"
    action = env.engine.propose(
        "drive_create_text_file",
        {"account": ACCOUNT, "name": "plan.md", "content": content, "mime": "text/markdown"},
        None,
    )
    assert drive.created == []
    assert content in action.preview
    assert ACCOUNT in action.preview and "plan.md" in action.preview
    assert "The file stays private to you; nothing is shared." in action.preview
    env.engine.decide(request_for(env.approval_key, action), DEVICE_ID)
    assert drive.created == [("plan.md", "text/markdown", content.encode())]
