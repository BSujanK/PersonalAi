"""Drive tools. Reads return untrusted data; the one WRITE only creates a private text file."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Any

from agent.connectors.drive import DriveApi, DriveFileNotFound
from agent.connectors.textextract import SUPPORTED_SUFFIXES, extract_text
from agent.core.tools import Tool, ToolKind, ToolRegistry

MAX_READ_TEXT = 8000
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
MAX_CONTENT_CHARS = 20_000
_FILE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CREATE_MIMES = ("text/plain", "text/markdown", "text/csv")
_GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

DriveApiFor = Callable[[str], DriveApi]


def _check_int(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def _check_account(value: Any, accounts: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in accounts:
        raise ValueError("account is not configured")
    return value


def _check_create(args: dict[str, Any], accounts: Sequence[str]) -> tuple[str, str, str, str]:
    account = _check_account(args.get("account"), accounts)
    name = args.get("name")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 200
        or "/" in name
        or "\\" in name
        or _CONTROL.search(name)
    ):
        raise ValueError("name must be 1 to 200 characters without slashes or control characters")
    content = args.get("content")
    if not isinstance(content, str) or len(content) > MAX_CONTENT_CHARS:
        raise ValueError(f"content must be a string of at most {MAX_CONTENT_CHARS} characters")
    mime = args.get("mime", "text/plain")
    if mime not in _CREATE_MIMES:
        raise ValueError("mime must be text/plain, text/markdown or text/csv")
    return account, name, content, mime


def register_drive_tools(
    registry: ToolRegistry, api_for: DriveApiFor, accounts: Sequence[str]
) -> None:
    def search(args: dict[str, Any]) -> Any:
        query = args.get("query")
        if query is not None and (not isinstance(query, str) or len(query) > 100):
            raise ValueError("query must be a string of at most 100 characters")
        limit = _check_int(args.get("limit", 10), 1, 20, "limit")
        account = args.get("account")
        targets = list(accounts) if account is None else [_check_account(account, accounts)]
        found: list[dict[str, Any]] = []
        for name in targets:
            for item in api_for(name).search(query or None, limit):
                found.append(
                    {
                        "account": name,
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "mime": item.get("mimeType"),
                        "modified": item.get("modifiedTime"),
                        "size": item.get("size"),
                    }
                )
        return found[:limit] if account is None else found

    def read(args: dict[str, Any]) -> Any:
        account = _check_account(args.get("account"), accounts)
        file_id = args.get("file_id")
        if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
            raise ValueError("file_id is not valid")
        api = api_for(account)
        try:
            meta = api.get_metadata(file_id)
            name = str(meta.get("name", ""))
            export_mime = _GOOGLE_EXPORTS.get(str(meta.get("mimeType", "")))
            if export_mime is not None:
                text = api.export(file_id, export_mime).decode("utf-8", errors="replace")
            else:
                suffix = PurePosixPath(name).suffix.lower()
                if suffix not in SUPPORTED_SUFFIXES:
                    return {"error": "unsupported file type"}
                try:
                    data = api.download(file_id, MAX_DOWNLOAD_BYTES)
                except ValueError:
                    return {"error": "file is too large"}
                text = extract_text(data, suffix)
        except DriveFileNotFound:
            return {"error": "file not found"}
        return {
            "account": account,
            "id": file_id,
            "name": name,
            "text": text[:MAX_READ_TEXT],
            "truncated": len(text) > MAX_READ_TEXT,
        }

    def create_preview(args: dict[str, Any]) -> str:
        account, name, content, mime = _check_create(args, accounts)
        return (
            f"Create a text file in Google Drive\n"
            f"Account: {account}\n"
            f"Name: {name}\n"
            f"Type: {mime}\n"
            f"Content:\n{content}\n"
            "The file stays private to you; nothing is shared."
        )

    def create_run(args: dict[str, Any]) -> Any:
        account, name, content, mime = _check_create(args, accounts)
        created = api_for(account).create_file(name, mime, content.encode("utf-8"))
        return {"id": created.get("id")}

    account_schema: dict[str, Any] = {"type": "string"}
    registry.register(
        Tool(
            name="drive_search",
            description="Search Google Drive files by text. Returns names and ids, not contents.",
            parameters={
                "type": "object",
                "properties": {
                    "account": account_schema,
                    "query": {"type": "string", "maxLength": 100},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=search,
        )
    )
    registry.register(
        Tool(
            name="drive_read",
            description="Read the text of one Google Drive file by account and file id.",
            parameters={
                "type": "object",
                "properties": {
                    "account": account_schema,
                    "file_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
                },
                "required": ["account", "file_id"],
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=read,
        )
    )
    registry.register(
        Tool(
            name="drive_create_text_file",
            description=(
                "Create a new private text file in Google Drive. Requires the owner's approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": account_schema,
                    "name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "content": {"type": "string", "maxLength": MAX_CONTENT_CHARS},
                    "mime": {"type": "string", "enum": list(_CREATE_MIMES)},
                },
                "required": ["account", "name", "content"],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=create_run,
            preview=create_preview,
        )
    )
