"""Mail tools. READ tools return untrusted data; WRITE tools only run after approval."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from agent.connectors.gmail import MAX_BATCH_IDS
from agent.core.clock import Clock
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.mail.digest import build_digest
from agent.mail.rules import CATEGORY_VALUES
from agent.mail.services import ApiFor
from agent.mail.store import MailStore, StoredMail

MAX_ITEMS = 100
MAX_READ_BODY = 8000
_SEARCH_SCAN = 500
_SYSTEM_LABELS = frozenset({"INBOX", "UNREAD", "STARRED", "IMPORTANT", "SPAM"})
_USER_LABEL = re.compile(r"Label_[0-9]+")
_SUBJECT_PREVIEW = 100

Item = tuple[str, str]  # (account, message_id)


def _check_int(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def _check_items(raw: Any) -> list[Item]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ITEMS:
        raise ValueError(f"items must be a list of 1 to {MAX_ITEMS} entries")
    items: dict[Item, None] = {}
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {"account", "message_id"}:
            raise ValueError("each item needs exactly account and message_id")
        account, message_id = entry["account"], entry["message_id"]
        if not (
            isinstance(account, str)
            and isinstance(message_id, str)
            and 0 < len(account) <= 254
            and 0 < len(message_id) <= 128
        ):
            raise ValueError("invalid item")
        items[(account, message_id)] = None
    return list(items)


def _check_labels(raw: Any, name: str) -> list[str]:
    if not isinstance(raw, list) or len(raw) > 10:
        raise ValueError(f"{name} must be a list of at most 10 labels")
    for label in raw:
        if not isinstance(label, str) or not (
            label in _SYSTEM_LABELS or _USER_LABEL.fullmatch(label)
        ):
            raise ValueError(f"label not allowed in {name}")
    return list(dict.fromkeys(raw))


def _line(text: str) -> str:
    """One display line for an approval preview: no control or format (bidi, zero-width) chars."""
    visible = "".join(
        " " if cat == "Cc" else ch for ch in text if (cat := unicodedata.category(ch)) != "Cf"
    )
    return " ".join(visible.split())[:_SUBJECT_PREVIEW]


def _summary(mail: StoredMail) -> dict[str, Any]:
    return {
        "id": mail.id,
        "account": mail.account,
        "from": f"{mail.from_name} <{mail.from_addr}>" if mail.from_name else mail.from_addr,
        "subject": mail.subject,
        "snippet": mail.snippet,
        "category": mail.category,
        "received_ms": mail.internal_date,
    }


_ITEMS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_ITEMS,
    "items": {
        "type": "object",
        "properties": {"account": {"type": "string"}, "message_id": {"type": "string"}},
        "required": ["account", "message_id"],
        "additionalProperties": False,
    },
}
_LABELS_SCHEMA: dict[str, Any] = {"type": "array", "items": {"type": "string"}, "maxItems": 10}


def register_mail_tools(
    registry: ToolRegistry, store: MailStore, api_for: ApiFor, clock: Clock
) -> None:
    def digest(args: dict[str, Any]) -> Any:
        hours = _check_int(args.get("hours", 24), 1, 168, "hours")
        return build_digest(store, clock(), hours).to_json()

    def search(args: dict[str, Any]) -> Any:
        query = args.get("query")
        if query is not None and (not isinstance(query, str) or len(query) > 100):
            raise ValueError("query must be a string of at most 100 characters")
        category = args.get("category")
        if category is not None and category not in CATEGORY_VALUES:
            raise ValueError("invalid category")
        account = args.get("account")
        if account is not None and not isinstance(account, str):
            raise ValueError("account must be a string")
        days = _check_int(args.get("days", 7), 1, 30, "days")
        limit = _check_int(args.get("limit", 10), 1, 20, "limit")
        since_ms = int((clock() - timedelta(days=days)).timestamp() * 1000)
        words = (query or "").lower().split()
        found: list[dict[str, Any]] = []
        for mail in store.recent(since_ms, account=account, category=category, limit=_SEARCH_SCAN):
            haystack = f"{mail.subject}\n{mail.from_addr}\n{mail.from_name}\n{mail.snippet}"
            if all(word in haystack.lower() for word in words):
                found.append(_summary(mail))
                if len(found) == limit:
                    break
        return found

    def read(args: dict[str, Any]) -> Any:
        account, message_id = args.get("account"), args.get("message_id")
        if not isinstance(account, str) or not isinstance(message_id, str):
            raise ValueError("account and message_id must be strings")
        mail = store.get(account, message_id)
        if mail is None:
            return {"error": "message not found"}
        return {
            **_summary(mail),
            "to": list(mail.to),
            "labels": list(mail.label_ids),
            "body": mail.body[:MAX_READ_BODY],
        }

    registry.register(
        Tool(
            name="mail_digest",
            description="Summarise recent mail: important messages and counts per category.",
            parameters={
                "type": "object",
                "properties": {"hours": {"type": "integer", "minimum": 1, "maximum": 168}},
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=digest,
        )
    )
    registry.register(
        Tool(
            name="mail_search",
            description=(
                "Find recent mail. Returns id, account, sender, subject and a short snippet per "
                "message, newest first; call mail_read with a result's account and id for the "
                "full text."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "maxLength": 100,
                        "description": "One or two topic words, such as exam or fee. Every word "
                        "must appear in the subject, sender or snippet, so leave out words like "
                        "email, professor or date.",
                    },
                    "category": {"type": "string", "enum": list(CATEGORY_VALUES)},
                    "account": {"type": "string", "description": "Omit to search every account."},
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 30,
                        "description": "How many days back to search (default 7).",
                    },
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
            name="mail_read",
            description=(
                "Read the full text of one message. Use the account and id exactly as "
                "mail_search or mail_digest returned them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "The result's account value."},
                    "message_id": {"type": "string", "description": "The result's id value."},
                },
                "required": ["account", "message_id"],
                "additionalProperties": False,
            },
            kind=ToolKind.READ,
            run=read,
        )
    )

    def preview_lines(header: str, items: list[Item]) -> str:
        lines = [header]
        for account, message_id in items:
            mail = store.get(account, message_id)
            if mail is None:
                lines.append(f"• [unknown message {_line(message_id)}]")
            else:
                who = mail.from_name or mail.from_addr
                lines.append(f"• {_line(who)} — {_line(mail.subject)} ({mail.account})")
        return "\n".join(lines)

    def plural(n: int) -> str:
        return f"{n} email" if n == 1 else f"{n} emails"

    def known_by_account(items: list[Item]) -> tuple[dict[str, list[str]], int]:
        """Group stored messages by account; unknown ones are skipped and counted."""
        grouped: dict[str, list[str]] = defaultdict(list)
        skipped = 0
        for account, message_id in items:
            if store.get_labels(account, message_id) is None:
                skipped += 1
            else:
                grouped[account].append(message_id)
        return grouped, skipped

    def modify(grouped: dict[str, list[str]], add: list[str], remove: list[str]) -> int:
        done = 0
        for account, ids in grouped.items():
            api = api_for(account)
            for start in range(0, len(ids), MAX_BATCH_IDS):
                chunk = ids[start : start + MAX_BATCH_IDS]
                api.batch_modify(chunk, add, remove)
                for message_id in chunk:
                    current = store.get_labels(account, message_id) or ()
                    labels = [x for x in current if x not in remove]
                    labels += [x for x in add if x not in labels]
                    store.update_labels(account, message_id, labels)
                done += len(chunk)
        return done

    def archive_preview(args: dict[str, Any]) -> str:
        items = _check_items(args.get("items"))
        return preview_lines(f"Archive {plural(len(items))}", items)

    def archive_run(args: dict[str, Any]) -> Any:
        items = _check_items(args.get("items"))
        grouped, skipped = known_by_account(items)
        return {"ok": modify(grouped, [], ["INBOX"]), "skipped": skipped}

    def trash_preview(args: dict[str, Any]) -> str:
        items = _check_items(args.get("items"))
        return preview_lines(f"Move {plural(len(items))} to trash", items)

    def trash_run(args: dict[str, Any]) -> Any:
        items = _check_items(args.get("items"))
        grouped, skipped = known_by_account(items)
        done = 0
        for account, ids in grouped.items():
            api = api_for(account)
            for message_id in ids:
                api.trash(message_id)
                store.mark_deleted(account, message_id)
                done += 1
        return {"ok": done, "skipped": skipped}

    def label_args(args: dict[str, Any]) -> tuple[list[Item], list[str], list[str]]:
        items = _check_items(args.get("items"))
        add = _check_labels(args.get("add", []), "add")
        remove = _check_labels(args.get("remove", []), "remove")
        if not add and not remove:
            raise ValueError("at least one label to add or remove is required")
        return items, add, remove

    def label_preview(args: dict[str, Any]) -> str:
        items, add, remove = label_args(args)
        changes = "; ".join(
            part
            for part in (
                f"add {', '.join(add)}" if add else "",
                f"remove {', '.join(remove)}" if remove else "",
            )
            if part
        )
        return preview_lines(f"Label {plural(len(items))} ({changes})", items)

    def label_run(args: dict[str, Any]) -> Any:
        items, add, remove = label_args(args)
        grouped, skipped = known_by_account(items)
        return {"ok": modify(grouped, add, remove), "skipped": skipped}

    def register_write(
        name: str,
        description: str,
        extra: dict[str, Any],
        run: Callable[[dict[str, Any]], Any],
        preview: Callable[[dict[str, Any]], str],
    ) -> None:
        registry.register(
            Tool(
                name=name,
                description=description + " Requires the owner's approval.",
                parameters={
                    "type": "object",
                    "properties": {"items": _ITEMS_SCHEMA, **extra},
                    "required": ["items"],
                    "additionalProperties": False,
                },
                kind=ToolKind.WRITE,
                run=run,
                preview=preview,
            )
        )

    register_write(
        "mail_archive", "Archive messages (remove from inbox).", {}, archive_run, archive_preview
    )
    register_write(
        "mail_trash",
        "Move messages to the trash (recoverable).",
        {},
        trash_run,
        trash_preview,
    )
    register_write(
        "mail_label",
        "Add or remove labels on messages.",
        {"add": _LABELS_SCHEMA, "remove": _LABELS_SCHEMA},
        label_run,
        label_preview,
    )
