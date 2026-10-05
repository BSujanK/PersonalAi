"""Local file tools. Read-only: there is no tool that writes, moves or deletes files."""

from __future__ import annotations

from typing import Any

from agent.connectors.files import FileAccessDenied, FileIndex, FileRoots
from agent.connectors.textextract import extract_text
from agent.core.tools import Tool, ToolKind, ToolRegistry

MAX_READ_TEXT = 8000
_DENIED = {"error": "path is not in an allowed folder"}


def _check_int(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def register_file_tools(registry: ToolRegistry, index: FileIndex, roots: FileRoots) -> None:
    def search(args: dict[str, Any]) -> Any:
        query = args.get("query")
        if not isinstance(query, str) or not 1 <= len(query) <= 100:
            raise ValueError("query must be a string of 1 to 100 characters")
        limit = _check_int(args.get("limit", 10), 1, 20, "limit")
        return [
            {"path": h.path, "name": h.name, "size": h.size, "modified": h.modified}
            for h in index.search(query, limit)
        ]

    def read(args: dict[str, Any]) -> Any:
        path = args.get("path")
        if not isinstance(path, str) or not 1 <= len(path) <= 1024:
            raise ValueError("path must be a string of 1 to 1024 characters")
        try:
            resolved = roots.resolve_inside(path)
            data = resolved.read_bytes()
        except (FileAccessDenied, OSError):
            return _DENIED
        text = extract_text(data, resolved.suffix)
        return {
            "path": str(resolved),
            "name": resolved.name,
            "text": text[:MAX_READ_TEXT],
            "truncated": len(text) > MAX_READ_TEXT,
        }

    registry.register(
        Tool(
            name="files_search",
            description="Search the owner's allowed local folders for files containing all words.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 100},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=search,
        )
    )
    registry.register(
        Tool(
            name="files_read",
            description="Read the text of one local file inside an allowed folder.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1024}},
                "required": ["path"],
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=read,
        )
    )
