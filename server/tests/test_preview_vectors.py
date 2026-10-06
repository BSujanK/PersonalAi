"""The phone parses approval previews for its badges; these vectors pin the format it relies on."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent.outbound.drive_tools import share_preview, upload_preview
from agent.outbound.mail_tools import mail_preview

VECTORS = Path(__file__).resolve().parents[2] / "shared" / "test-vectors" / "action-previews.json"
PREVIEWS: dict[str, Callable[[dict[str, Any]], str]] = {
    "mail_send": mail_preview,
    "mail_reply": mail_preview,
    "drive_share": share_preview,
    "drive_upload": upload_preview,
}


def _vectors() -> list[tuple[str, dict[str, Any]]]:
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    return [(name, v) for name, v in data.items() if not name.startswith("_")]


@pytest.mark.parametrize(("name", "vector"), _vectors())
def test_server_preview_matches_the_shared_vector(name: str, vector: dict[str, Any]) -> None:
    assert PREVIEWS[vector["tool"]](vector["payload"]) == vector["preview"], name
