"""Google Drive access the agent needs. Implemented in ``drive_google``; faked in tests."""

from __future__ import annotations

from typing import Any, Protocol


class DriveFileNotFound(Exception):
    """The file does not exist or is not visible to the account."""


class DriveApi(Protocol):
    def search(self, query: str | None, limit: int) -> list[dict[str, Any]]:
        """Non-trashed files, optionally matching full text. Metadata fields only."""
        ...

    def get_metadata(self, file_id: str) -> dict[str, Any]: ...

    def export(self, file_id: str, mime: str) -> bytes:
        """Export a Google-native document (Docs, Sheets, Slides) as ``mime``."""
        ...

    def download(self, file_id: str, max_bytes: int) -> bytes:
        """Raw content of a stored file. Raises ``ValueError`` if it exceeds ``max_bytes``."""
        ...

    def create_file(self, name: str, mime: str, content: bytes) -> dict[str, Any]:
        """Create a new private file owned by the account."""
        ...
