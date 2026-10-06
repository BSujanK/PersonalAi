"""``DriveApi`` over google-api-python-client. Credentials live only in the OS keyring."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from agent.connectors.drive import DriveFileNotFound
from agent.connectors.google_auth import DRIVE, DRIVE_READONLY, GoogleAuth

_RETRIES = 3
_FIELDS = "id,name,mimeType,modifiedTime,size"
_META_FIELDS = f"{_FIELDS},md5Checksum,webViewLink"
_SIMPLE_UPLOAD_MAX = 5 * 1024 * 1024  # larger uploads must use the resumable protocol


def _status(exc: HttpError) -> int | None:
    status = getattr(exc.resp, "status", None)
    return int(status) if status is not None else None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveApi:
    def __init__(self, service: Any, after_call: Callable[[], None] | None = None) -> None:
        self._service = service
        self._after_call = after_call

    def _execute(self, request: Any) -> Any:
        try:
            result = request.execute(num_retries=_RETRIES)
        except HttpError as exc:
            if _status(exc) == 404:
                raise DriveFileNotFound from None
            raise
        if self._after_call is not None:
            self._after_call()
        return result

    def search(self, query: str | None, limit: int) -> list[dict[str, Any]]:
        q = "trashed = false"
        if query:
            q += f" and fullText contains '{_escape(query)}'"
        result = self._execute(
            self._service.files().list(
                q=q,
                pageSize=limit,
                fields=f"files({_FIELDS})",
                orderBy="modifiedTime desc",
            )
        )
        files: list[dict[str, Any]] = result.get("files", [])
        return files

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._execute(
            self._service.files().get(fileId=file_id, fields=_META_FIELDS)
        )
        return result

    def export(self, file_id: str, mime: str) -> bytes:
        result = self._execute(self._service.files().export(fileId=file_id, mimeType=mime))
        return bytes(result)

    def download(self, file_id: str, max_bytes: int) -> bytes:
        meta = self.get_metadata(file_id)
        if int(meta.get("size", 0)) > max_bytes:
            raise ValueError("file is larger than the allowed size")
        result = self._execute(self._service.files().get_media(fileId=file_id))
        data = bytes(result)
        if len(data) > max_bytes:
            raise ValueError("file is larger than the allowed size")
        return data

    def create_file(
        self, name: str, mime: str, content: bytes, parent: str | None = None
    ) -> dict[str, Any]:
        media = MediaIoBaseUpload(
            io.BytesIO(content), mimetype=mime, resumable=len(content) > _SIMPLE_UPLOAD_MAX
        )
        body: dict[str, Any] = {"name": name, "mimeType": mime}
        if parent is not None:
            body["parents"] = [parent]
        result: dict[str, Any] = self._execute(
            self._service.files().create(body=body, media_body=media, fields=_META_FIELDS)
        )
        return result

    def share(self, file_id: str, permission: dict[str, Any], notify: bool) -> dict[str, Any]:
        result: dict[str, Any] = self._execute(
            self._service.permissions().create(
                fileId=file_id, body=permission, sendNotificationEmail=notify, fields="id"
            )
        )
        return result


def build_drive_api(account: str, auth: GoogleAuth) -> GoogleDriveApi:
    credentials = auth.credentials(account, [DRIVE_READONLY, DRIVE])
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return GoogleDriveApi(service, auth.persist_hook(account))
