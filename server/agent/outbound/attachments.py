"""Attachments from allowlisted local files or Drive, pinned by size and checksum at proposal."""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.connectors.drive import DriveApi, DriveFileNotFound
from agent.connectors.files import FileAccessDenied, FileRoots
from agent.core.tools import ActionRejected
from agent.outbound.recipients import display

MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 10
_FILE_ID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."
FOLDER_MIME = "application/vnd.google-apps.folder"

DriveApiFor = Callable[[str], DriveApi]


class AttachmentChanged(RuntimeError):
    """The file changed (or vanished) after the owner saw it in the preview."""


@dataclass(frozen=True)
class Sources:
    """Where attachments may come from. A missing source refuses attachments of that kind."""

    roots: FileRoots | None = None
    drive_for: DriveApiFor | None = None
    drive_accounts: Sequence[str] = field(default_factory=tuple)


def check_drive_account(value: Any, sources: Sources) -> str:
    if sources.drive_for is None or not isinstance(value, str):
        raise ActionRejected("Drive is not configured for that account")
    account = value.strip().lower()
    if account not in {a.lower() for a in sources.drive_accounts}:
        raise ActionRejected("Drive is not configured for that account")
    return account


def check_file_id(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or set(value) - _FILE_ID_CHARS:
        raise ActionRejected("file_id is not valid; copy it from a drive_search result")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_local(path: Any, sources: Sources) -> tuple[Path, bytes]:
    if sources.roots is None:
        raise ActionRejected("no local folders are allowed")
    if not isinstance(path, str) or not 1 <= len(path) <= 1024:
        raise ActionRejected("path must be a string of 1 to 1024 characters")
    try:
        resolved = sources.roots.resolve_inside(path, any_type=True)
        return resolved, resolved.read_bytes()
    except (FileAccessDenied, OSError):
        raise ActionRejected(
            "that file is not in an allowed folder; copy a path from files_search"
        ) from None


def local_entry(path: Path, data: bytes) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "source": "local",
        "path": str(path),
        "name": path.name,
        "size": len(data),
        "mime": mime,
        "sha256": _sha256(data),
    }


def drive_metadata(account: str, file_id: str, sources: Sources) -> dict[str, Any]:
    assert sources.drive_for is not None  # noqa: S101 - checked by check_drive_account
    try:
        return sources.drive_for(account).get_metadata(file_id)
    except DriveFileNotFound:
        raise ActionRejected("Drive file not found; copy the id from drive_search") from None


def _drive_entry(account: str, file_id: str, sources: Sources) -> dict[str, Any]:
    meta = drive_metadata(account, file_id, sources)
    mime = str(meta.get("mimeType", "application/octet-stream"))
    if mime.startswith(GOOGLE_NATIVE_PREFIX):
        raise ActionRejected(
            "Google Docs, Sheets, Slides and folders cannot be attached; use drive_share instead"
        )
    size = meta.get("size")
    if not isinstance(size, int | str) or not str(size).isdigit():
        raise ActionRejected("that Drive file has no known size")
    return {
        "source": "drive",
        "account": account,
        "file_id": file_id,
        "name": display(str(meta.get("name", file_id))) or file_id,
        "size": int(size),
        "mime": mime,
        "md5": str(meta.get("md5Checksum", "")),
    }


def prepare_attachments(raw: Any, sources: Sources) -> list[dict[str, Any]]:
    """Resolve the model's attachment list. Raises ``ActionRejected`` with fixed text."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENTS:
        raise ActionRejected(f"attachments must be a list of at most {MAX_ATTACHMENTS} files")
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ActionRejected("each attachment must be an object")
        source = item.get("source")
        if source == "local" and set(item) == {"source", "path"}:
            entries.append(local_entry(*resolve_local(item["path"], sources)))
        elif source == "drive" and set(item) == {"source", "account", "file_id"}:
            account = check_drive_account(item["account"], sources)
            entries.append(_drive_entry(account, check_file_id(item["file_id"]), sources))
        else:
            raise ActionRejected(
                'each attachment is {"source": "local", "path": ...} or '
                '{"source": "drive", "account": ..., "file_id": ...}'
            )
    if sum(e["size"] for e in entries) > MAX_TOTAL_BYTES:
        raise ActionRejected("attachments are larger than 20 MB in total; share a Drive link")
    return entries


def load_attachment(entry: dict[str, Any], sources: Sources) -> bytes:
    """The bytes of a pinned attachment; ``AttachmentChanged`` if they differ from the preview."""
    if entry["source"] == "local":
        if sources.roots is None:
            raise AttachmentChanged("local files are no longer allowed")
        try:
            path = sources.roots.resolve_inside(entry["path"], any_type=True)
            data = path.read_bytes()
        except (FileAccessDenied, OSError):
            raise AttachmentChanged("file is gone or no longer allowed") from None
        if len(data) != entry["size"] or _sha256(data) != entry["sha256"]:
            raise AttachmentChanged("file changed after it was approved")
        return data
    if sources.drive_for is None:
        raise AttachmentChanged("Drive is no longer configured")
    try:
        data = sources.drive_for(entry["account"]).download(entry["file_id"], entry["size"])
    except (DriveFileNotFound, ValueError):
        raise AttachmentChanged("Drive file is gone or changed") from None
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    if len(data) != entry["size"] or (entry["md5"] and md5 != entry["md5"]):
        raise AttachmentChanged("Drive file changed after it was approved")
    return data


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def attachment_lines(entries: list[dict[str, Any]]) -> list[str]:
    if not entries:
        return ["Attachments: (none)"]
    total = human_size(sum(e["size"] for e in entries))
    lines = [f"Attachments ({len(entries)}, {total} total):"]
    for e in entries:
        where = (
            f"local file {display(e['path'], 400)}"
            if e["source"] == "local"
            else f"Google Drive of {e['account']} (id {e['file_id']})"
        )
        lines.append(f"  • {display(e['name'])} — {human_size(e['size'])} — {e['mime']} — {where}")
    return lines
