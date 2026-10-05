from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import Settings
from agent.connectors.google_auth import GoogleAuth
from agent.core.clock import utcnow
from agent.core.tools import ToolKind, ToolRegistry
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.workspace.services import setup_workspace

EXPECTED = {
    "calendar_events": ToolKind.READ,
    "calendar_create_event": ToolKind.WRITE,
    "calendar_update_event": ToolKind.WRITE,
    "calendar_add_deadline": ToolKind.WRITE,
    "classroom_courses": ToolKind.READ,
    "classroom_coursework": ToolKind.READ,
    "classroom_announcements": ToolKind.READ,
    "classroom_materials": ToolKind.READ,
    "drive_search": ToolKind.READ,
    "drive_read": ToolKind.READ,
    "drive_create_text_file": ToolKind.WRITE,
    "files_search": ToolKind.READ,
    "files_read": ToolKind.READ,
}


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    base: dict[str, object] = {
        "calendar_accounts": ("me@example.com",),
        "classroom_accounts": ("student@example.edu",),
        "drive_accounts": ("me@example.com",),
        "file_roots": (str(docs),),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_every_m3_tool_has_the_expected_kind(tmp_path: Path) -> None:
    registry = ToolRegistry()
    services = setup_workspace(
        _settings(tmp_path),
        Database(":memory:"),
        bytes(32),
        registry,
        GoogleAuth(KeyStore()),
        utcnow,
    )
    assert {name: registry.kind_of(name) for name in EXPECTED} == EXPECTED
    assert services.file_index is not None
    assert services.classroom_api_for is not None
    names = {schema["function"]["name"] for schema in registry.schemas()}
    # Read-only by design: no share, delete or file-write tools exist.
    assert not {n for n in names if any(w in n for w in ("share", "delete", "permission"))}
    assert not {
        n for n in names if n.startswith("files_") and registry.kind_of(n) is ToolKind.WRITE
    }


def test_nothing_is_registered_without_configuration() -> None:
    registry = ToolRegistry()
    services = setup_workspace(
        Settings(), Database(":memory:"), bytes(32), registry, GoogleAuth(KeyStore()), utcnow
    )
    assert registry.schemas() == []
    assert services.file_index is None


def test_deadline_calendar_must_be_a_calendar_account(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        setup_workspace(
            _settings(tmp_path, deadline_calendar_account="other@example.com"),
            Database(":memory:"),
            bytes(32),
            ToolRegistry(),
            GoogleAuth(KeyStore()),
            utcnow,
        )
