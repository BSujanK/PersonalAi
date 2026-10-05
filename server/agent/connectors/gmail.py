"""Gmail data model, message parsing and the API protocol the rest of the agent depends on."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from email.errors import HeaderParseError
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses
from html import unescape
from html.parser import HTMLParser
from typing import Any, Protocol

MAX_BODY_CHARS = 100_000
MAX_BATCH_IDS = 1000


class MalformedMessage(ValueError):
    """A Gmail message resource did not have the expected shape."""


class HistoryExpired(RuntimeError):
    """The stored history id is too old; a full sync is required."""


class MessageNotFound(LookupError):
    """The message no longer exists (deleted between listing and fetching)."""


@dataclass(frozen=True)
class MailMessage:
    account: str
    id: str
    thread_id: str
    history_id: str
    internal_date: int  # milliseconds since the epoch
    from_addr: str
    from_name: str
    to: tuple[str, ...]  # To and Cc addresses
    subject: str
    snippet: str
    body: str
    label_ids: tuple[str, ...]
    list_unsubscribe: bool


class GmailApi(Protocol):
    def profile(self) -> dict[str, Any]: ...

    def list_message_ids(
        self, query: str, page_token: str | None
    ) -> tuple[list[str], str | None]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...

    def list_history(
        self, start_history_id: str, page_token: str | None
    ) -> tuple[list[dict[str, Any]], str, str | None]: ...

    def batch_modify(self, ids: list[str], add: list[str], remove: list[str]) -> None: ...

    def trash(self, message_id: str) -> None: ...


_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
)


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in joined.split("\n"))
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    return parser.text()


def _decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, HeaderParseError):
        return value


def _decode_data(data: str, charset: str | None) -> str:
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError) as exc:
        raise MalformedMessage("invalid base64 body") from exc
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    for header in payload.get("headers") or []:
        if not isinstance(header, dict):
            raise MalformedMessage("invalid header entry")
        name, value = header.get("name"), header.get("value")
        if isinstance(name, str) and isinstance(value, str):
            found.setdefault(name.lower(), value)
    return found


def _charset(headers: dict[str, str]) -> str | None:
    content_type = headers.get("content-type")
    if content_type is None:
        return None
    probe = Message()
    probe["Content-Type"] = content_type
    charset = probe.get_content_charset()
    return charset if isinstance(charset, str) else None


def _collect_bodies(
    part: dict[str, Any], plain: list[str], html: list[str], depth: int = 0
) -> None:
    if depth > 20:
        raise MalformedMessage("message nesting too deep")
    sub_parts = part.get("parts")
    if isinstance(sub_parts, list):
        for sub in sub_parts:
            if not isinstance(sub, dict):
                raise MalformedMessage("invalid message part")
            _collect_bodies(sub, plain, html, depth + 1)
        return
    body = part.get("body")
    if not isinstance(body, dict) or part.get("filename") or "attachmentId" in body:
        return
    data = body.get("data")
    if not isinstance(data, str) or not data:
        return
    mime = str(part.get("mimeType", "")).lower()
    if mime not in ("text/plain", "text/html"):
        return
    text = _decode_data(data, _charset(_headers(part)))
    (plain if mime == "text/plain" else html).append(text)


def _addresses(value: str | None) -> list[tuple[str, str]]:
    if not value:
        return []
    return [
        (_decode_header_value(name).strip(), addr.strip().lower())
        for name, addr in getaddresses([value])
        if addr.strip()
    ]


def parse_message(account: str, resource: dict[str, Any]) -> MailMessage:
    """Convert a Gmail ``format=full`` message resource. Raises ``MalformedMessage``."""
    try:
        message_id = resource["id"]
        thread_id = resource["threadId"]
        history_id = str(resource["historyId"])
        internal_date = int(resource["internalDate"])
        payload = resource["payload"]
    except (KeyError, TypeError, ValueError) as exc:
        raise MalformedMessage("missing or invalid message field") from exc
    if not isinstance(message_id, str) or not isinstance(thread_id, str):
        raise MalformedMessage("invalid message id")
    if not isinstance(payload, dict):
        raise MalformedMessage("invalid payload")
    labels = resource.get("labelIds") or []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise MalformedMessage("invalid labelIds")
    headers = _headers(payload)
    senders = _addresses(headers.get("from"))
    from_name, from_addr = senders[0] if senders else ("", "")
    recipients = tuple(
        addr for _, addr in _addresses(headers.get("to")) + _addresses(headers.get("cc"))
    )
    plain: list[str] = []
    html: list[str] = []
    _collect_bodies(payload, plain, html)
    body = "\n".join(plain) if plain else html_to_text("\n".join(html))
    subject = _decode_header_value(headers.get("subject", ""))
    return MailMessage(
        account=account,
        id=message_id,
        thread_id=thread_id,
        history_id=history_id,
        internal_date=internal_date,
        from_addr=from_addr,
        from_name=from_name,
        to=recipients,
        subject=subject,
        snippet=unescape(str(resource.get("snippet", ""))),
        body=body[:MAX_BODY_CHARS],
        label_ids=tuple(labels),
        list_unsubscribe="list-unsubscribe" in headers,
    )
