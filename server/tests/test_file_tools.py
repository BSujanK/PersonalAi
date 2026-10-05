from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.connectors.files import FileIndex, FileRoots
from agent.core.tools import ToolKind, ToolRegistry
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.workspace.file_tools import register_file_tools
from tests.support import FakeClock

KEY = bytes(range(32))


@pytest.fixture
def env(tmp_path: Path) -> tuple[ToolRegistry, Path]:
    root = tmp_path / "docs"
    root.mkdir()
    roots = FileRoots([str(root)])
    index = FileIndex(Database(":memory:"), FieldCipher(KEY), KEY, roots, FakeClock())
    (root / "notes.txt").write_text("synthetic itinerary for lisbon")
    (root / "long.txt").write_text("w" * 9000)
    index.refresh()
    registry = ToolRegistry()
    register_file_tools(registry, index, roots)
    return registry, root


def _run(registry: ToolRegistry, name: str, args: dict[str, Any]) -> Any:
    tool = registry.get(name)
    assert tool is not None
    return tool.run(args)


def test_only_read_tools_exist(env: tuple[ToolRegistry, Path]) -> None:
    registry, _ = env
    assert registry.kind_of("files_search") is ToolKind.READ
    assert registry.kind_of("files_read") is ToolKind.READ
    assert {s["function"]["name"] for s in registry.schemas()} == {"files_search", "files_read"}


def test_search_returns_hits_and_validates(env: tuple[ToolRegistry, Path]) -> None:
    registry, root = env
    hits = _run(registry, "files_search", {"query": "lisbon"})
    assert hits == [
        {
            "path": str((root / "notes.txt").resolve()),
            "name": "notes.txt",
            "size": len("synthetic itinerary for lisbon"),
            "modified": hits[0]["modified"],
        }
    ]
    for bad in (
        {},
        {"query": ""},
        {"query": "x" * 101},
        {"query": "a", "limit": 0},
        {"query": "a", "limit": 21},
    ):
        with pytest.raises(ValueError):
            _run(registry, "files_search", bad)


def test_read_live_from_disk_and_truncates(env: tuple[ToolRegistry, Path]) -> None:
    registry, root = env
    (root / "notes.txt").write_text("changed after indexing")
    result = _run(registry, "files_read", {"path": str(root / "notes.txt")})
    assert result["text"] == "changed after indexing"
    assert result["name"] == "notes.txt"
    assert result["truncated"] is False
    long = _run(registry, "files_read", {"path": str(root / "long.txt")})
    assert len(long["text"]) == 8000 and long["truncated"] is True


def test_read_outside_root_is_denied_without_echoing_path(
    env: tuple[ToolRegistry, Path], tmp_path: Path
) -> None:
    registry, root = env
    (tmp_path / "private.txt").write_text("nope")
    for target in (str(tmp_path / "private.txt"), str(root / ".." / "private.txt")):
        result = _run(registry, "files_read", {"path": target})
        assert result == {"error": "path is not in an allowed folder"}
        assert "private" not in str(result)
    with pytest.raises(ValueError):
        _run(registry, "files_read", {"path": "x" * 1025})
