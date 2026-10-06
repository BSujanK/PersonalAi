from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.connectors.files import FileIndex, FileRoots
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.workspace.drive_tools import register_drive_tools
from agent.workspace.file_tools import register_file_tools
from tests.support import FakeClock
from tests.test_api import _auth
from tests.test_drive_tools import FakeDrive
from tests.test_loop import FakeLLM, say

KEY = bytes(range(32))
ACCOUNT = "me@example.com"


def _client(registry: ToolRegistry) -> tuple[TestClient, dict[str, str]]:
    db = Database(":memory:")
    clock = FakeClock()
    app = create_app(
        Settings(owner_emails=(ACCOUNT,)),
        db=db,
        keystore=KeyStore(),
        llm=FakeLLM(say("hi")),
        registry=registry,
        clock=clock,
    )
    client = TestClient(app)
    code = open_pairing_window(db, clock, 300)
    paired = client.post("/pair", json={"code": code, "device_name": "Pixel"}).json()
    return client, _auth(paired)


def _registry(tmp_path: Path, drive: FakeDrive | None = None) -> tuple[ToolRegistry, Path]:
    root = tmp_path / "docs"
    root.mkdir()
    roots = FileRoots([str(root)])
    index = FileIndex(Database(":memory:"), FieldCipher(KEY), KEY, roots, FakeClock())
    (root / "itinerary.txt").write_text("synthetic itinerary for lisbon")
    index.refresh()
    registry = ToolRegistry()
    register_file_tools(registry, index, roots)
    if drive is not None:
        register_drive_tools(registry, lambda _account: drive, [ACCOUNT])
    return registry, root


def test_search_returns_local_and_drive_hits(tmp_path: Path) -> None:
    drive = FakeDrive()
    registry, root = _registry(tmp_path, drive)
    client, headers = _client(registry)
    resp = client.get("/files/search", params={"q": "lisbon", "limit": 5}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["errors"] == []
    assert len(body["local"]) == 1
    hit = body["local"][0]
    assert hit["source"] == "local"
    assert hit["path"] == str((root / "itinerary.txt").resolve())
    assert hit["name"] == "itinerary.txt"
    assert isinstance(hit["size"], int)
    assert body["drive"] == [
        {
            "source": "drive",
            "account": ACCOUNT,
            "id": "f1",
            "name": "Notes",
            "mime": "text/plain",
            "size": 5,
            "modified": "2026-10-01T00:00:00Z",
        }
    ]
    assert drive.search_calls == [("lisbon", 5)]


def test_unconfigured_sources_are_null(tmp_path: Path) -> None:
    client, headers = _client(ToolRegistry())
    body = client.get("/files/search", params={"q": "x"}, headers=headers).json()
    assert body == {"local": None, "drive": None, "errors": []}


def test_a_failing_source_does_not_hide_the_other(tmp_path: Path) -> None:
    class BrokenDrive(FakeDrive):
        def search(self, query: str | None, limit: int) -> list[dict[str, Any]]:
            raise RuntimeError("drive down")

    registry, _ = _registry(tmp_path, BrokenDrive())
    client, headers = _client(registry)
    body = client.get("/files/search", params={"q": "lisbon"}, headers=headers).json()
    assert body["errors"] == ["drive"]
    assert body["drive"] is None
    assert len(body["local"]) == 1


def test_only_read_tools_are_run(tmp_path: Path) -> None:
    ran: list[dict[str, Any]] = []
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="files_search",
            description="a WRITE tool must never run from this route",
            parameters={"type": "object"},
            kind=ToolKind.WRITE,
            run=lambda args: ran.append(args),
            preview=lambda args: "preview",
        )
    )
    client, headers = _client(registry)
    body = client.get("/files/search", params={"q": "x"}, headers=headers).json()
    assert body["local"] is None
    assert ran == []


def test_requires_token_and_validates_query(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    client, headers = _client(registry)
    assert client.get("/files/search", params={"q": "lisbon"}).status_code == 401
    assert client.get("/files/search", params={"q": ""}, headers=headers).status_code == 422
    assert client.get("/files/search", params={"q": "x" * 101}, headers=headers).status_code == 422
    assert (
        client.get("/files/search", params={"q": "x", "limit": 21}, headers=headers).status_code
        == 422
    )
