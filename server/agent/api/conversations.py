"""Conversation history for the phone: list, open, rename and delete.

This is the only place stored conversations are rehydrated for display. The text goes to the
owner's phone over the device-token-protected API; it is never sent to the LLM, and nothing here
changes what ``/chat`` sends to the model. Titles are derived locally from the first user message
(no LLM call) and stored encrypted next to the conversation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent.core.redact import RedactionMap, Redactor
from agent.core.sources import Source
from agent.store.crypto import FieldCipher
from agent.store.db import Database

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_TITLE = "New chat"
TITLE_MAX = 60
PREVIEW_MAX = 120
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SPACE = re.compile(r"\s+")
_MARKUP = re.compile(r"[*_`#>~\[\]]+")

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_titles (
    conversation_id TEXT PRIMARY KEY,
    title_enc BLOB NOT NULL,
    user_set INTEGER NOT NULL DEFAULT 0
);
"""


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    preview: str


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None


class ToolRun(BaseModel):
    name: str
    status: Literal["finished", "failed"]


class DisplayMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: str
    tools: list[ToolRun] = Field(default_factory=list)
    pending_action_ids: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    id: str
    title: str
    updated_at: str
    messages: list[DisplayMessage]


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def make_title(text: str) -> str:
    """Local auto-title: the first user line, markup stripped, cut at a word boundary."""
    flat = _SPACE.sub(" ", _MARKUP.sub("", text)).strip()
    if not flat:
        return DEFAULT_TITLE
    if len(flat) <= TITLE_MAX:
        return flat
    cut = flat[:TITLE_MAX].rsplit(" ", 1)[0] or flat[:TITLE_MAX]
    return cut.rstrip(" ,.;:-") + "…"


def _tool_name(raw: object) -> str:
    # Names come from the model; only well-formed ones are shown.
    return raw if isinstance(raw, str) and _TOOL_NAME.match(raw) else "unknown"


def _stored_sources(raw: object) -> list[Source]:
    """Sources saved with a final reply; a malformed entry is skipped, never shown."""
    found: list[Source] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            found.append(Source.model_validate(item))
        except ValueError:
            continue
    return found


class _Stored:
    """One decoded stored message row (still in placeholder space)."""

    __slots__ = ("content", "created_at", "id", "role", "sources", "tool_call_id", "tool_calls")

    def __init__(self, row: Any, data: dict[str, Any]) -> None:
        self.id: str = row["id"]
        self.role: str = row["role"]
        self.created_at: str = row["created_at"]
        self.content: str = data.get("content") or ""
        self.tool_call_id: str | None = data.get("tool_call_id")
        self.tool_calls: list[dict[str, Any]] = data.get("tool_calls") or []
        self.sources: list[Source] = _stored_sources(data.get("sources"))


class ConversationStore:
    def __init__(self, db: Database, cipher: FieldCipher) -> None:
        self._db = db
        self._cipher = cipher
        with db.transaction():
            for statement in _META_SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)

    # -- loading -------------------------------------------------------------------------

    def _rmap(self, row: Any) -> RedactionMap:
        blob = row["redaction_map_enc"]
        if not blob:
            return RedactionMap()
        return RedactionMap.from_json(
            self._cipher.decrypt_str(blob, f"conversations.redaction_map:{row['id']}")
        )

    def _messages(self, conversation_id: str) -> list[_Stored]:
        out: list[_Stored] = []
        for r in self._db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq", (conversation_id,)
        ):
            text = self._cipher.decrypt_str(r["content_enc"], f"messages.content:{r['id']}")
            out.append(_Stored(r, json.loads(text)))
        return out

    def _get_row(self, conversation_id: str) -> Any | None:
        rows = self._db.query("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        return rows[0] if rows else None

    def _updated_at(self, row: Any) -> str:
        found = self._db.query(
            "SELECT MAX(created_at) AS t FROM messages WHERE conversation_id = ?", (row["id"],)
        )
        value = found[0]["t"] if found else None
        return str(value) if value else str(row["created_at"])

    # -- titles --------------------------------------------------------------------------

    def _stored_title(self, conversation_id: str) -> str | None:
        rows = self._db.query(
            "SELECT title_enc FROM conversation_titles WHERE conversation_id = ?",
            (conversation_id,),
        )
        if not rows:
            return None
        return self._cipher.decrypt_str(
            rows[0]["title_enc"], f"conversation_titles.title:{conversation_id}"
        )

    def _save_title(self, conversation_id: str, title: str, *, user_set: bool) -> None:
        blob = self._cipher.encrypt(title, f"conversation_titles.title:{conversation_id}")
        self._db.execute(
            "INSERT INTO conversation_titles (conversation_id, title_enc, user_set) "
            "VALUES (?, ?, ?) ON CONFLICT(conversation_id) DO UPDATE SET "
            "title_enc = excluded.title_enc, user_set = excluded.user_set",
            (conversation_id, blob, int(user_set)),
        )

    def _title(self, row: Any, messages: list[_Stored], rmap: RedactionMap) -> str:
        """Stored title, or one derived from the first user message and then stored."""
        stored = self._stored_title(row["id"])
        if stored is not None:
            return stored
        first = next((m for m in messages if m.role == "user"), None)
        title = make_title(Redactor.rehydrate(first.content, rmap)) if first else DEFAULT_TITLE
        if first is not None:  # an empty conversation keeps deriving until it has a message
            self._save_title(row["id"], title, user_set=False)
        return title

    # -- views ---------------------------------------------------------------------------

    @staticmethod
    def _last_line(text: str) -> str:
        for line in reversed(text.splitlines()):
            flat = _SPACE.sub(" ", _MARKUP.sub("", line)).strip()
            if flat:
                return flat if len(flat) <= PREVIEW_MAX else flat[: PREVIEW_MAX - 1] + "…"
        return ""

    def _summary(self, row: Any) -> ConversationSummary:
        rmap = self._rmap(row)
        messages = self._messages(row["id"])
        reply = next(
            (m for m in reversed(messages) if m.role == "assistant" and not m.tool_calls), None
        )
        preview = self._last_line(Redactor.rehydrate(reply.content, rmap)) if reply else ""
        return ConversationSummary(
            id=row["id"],
            title=self._title(row, messages, rmap),
            updated_at=self._updated_at(row),
            preview=preview,
        )

    def page(self, limit: int, cursor: str | None, query: str | None) -> ConversationPage:
        rows = self._db.query(
            "SELECT c.*, COALESCE(MAX(m.created_at), c.created_at) AS updated "
            "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
            "GROUP BY c.id ORDER BY updated DESC, c.id DESC"
        )
        if cursor:
            stamp, _, last_id = cursor.partition("|")
            rows = [r for r in rows if (r["updated"], r["id"]) < (stamp, last_id)]
        needle = query.strip().casefold() if query else ""
        items: list[ConversationSummary] = []
        last: tuple[str, str] | None = None
        more = False
        for r in rows:
            summary = self._summary(r)
            if needle and needle not in summary.title.casefold():
                continue
            if len(items) == limit:
                more = True
                break
            items.append(summary)
            last = (r["updated"], r["id"])
        next_cursor = f"{last[0]}|{last[1]}" if more and last else None
        return ConversationPage(items=items, next_cursor=next_cursor)

    def detail(self, conversation_id: str) -> ConversationDetail | None:
        row = self._get_row(conversation_id)
        if row is None:
            return None
        rmap = self._rmap(row)
        stored = self._messages(conversation_id)
        return ConversationDetail(
            id=conversation_id,
            title=self._title(row, stored, rmap),
            updated_at=self._updated_at(row),
            messages=_display(stored, rmap),
        )

    def rename(self, conversation_id: str, title: str) -> ConversationSummary | None:
        row = self._get_row(conversation_id)
        if row is None:
            return None
        clean = _SPACE.sub(" ", title).strip()
        if not clean:
            raise ValueError("empty title")
        self._save_title(conversation_id, clean[:200], user_set=True)
        return self._summary(row)

    def delete(self, conversation_id: str) -> bool:
        """Remove the conversation and its messages. Approval records are kept for the audit."""
        if self._get_row(conversation_id) is None:
            return False
        with self._db.transaction():
            self._db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            self._db.execute(
                "DELETE FROM conversation_titles WHERE conversation_id = ?", (conversation_id,)
            )
            self._db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return True


def _display(stored: list[_Stored], rmap: RedactionMap) -> list[DisplayMessage]:
    """Fold the raw transcript into user messages and one assistant message per turn."""
    out: list[DisplayMessage] = []
    turn: list[_Stored] = []

    def flush() -> None:
        if not turn:
            return
        # Each tool message answers the latest unanswered call with the same id.
        calls: list[dict[str, Any]] = []
        for m in turn:
            if m.role == "assistant":
                calls.extend(
                    {"id": c.get("id"), "name": c.get("name"), "result": None} for c in m.tool_calls
                )
            elif m.role == "tool":
                for entry in reversed(calls):
                    if entry["id"] == m.tool_call_id and entry["result"] is None:
                        entry["result"] = m.content
                        break
        runs: list[ToolRun] = []
        action_ids: list[str] = []
        for entry in calls:
            result = entry["result"] or ""
            status: Literal["finished", "failed"] = (
                "failed" if result.startswith("error:") else "finished"
            )
            runs.append(ToolRun(name=_tool_name(entry["name"]), status=status))
            action_id = _action_id(result)
            if action_id:
                action_ids.append(action_id)
        final = next(
            (m for m in reversed(turn) if m.role == "assistant" and not m.tool_calls), None
        )
        last = turn[-1]
        out.append(
            DisplayMessage(
                id=(final or last).id,
                role="assistant",
                text=Redactor.rehydrate(final.content, rmap) if final else "",
                created_at=(final or last).created_at,
                tools=runs,
                pending_action_ids=action_ids,
                sources=final.sources if final else [],
            )
        )
        turn.clear()

    for m in stored:
        if m.role == "user":
            flush()
            out.append(
                DisplayMessage(
                    id=m.id,
                    role="user",
                    text=Redactor.rehydrate(m.content, rmap),
                    created_at=m.created_at,
                )
            )
        elif m.role in ("assistant", "tool"):
            turn.append(m)
    flush()
    return out


def _action_id(tool_result: str) -> str | None:
    if "pending_approval" not in tool_result:
        return None
    try:
        data = json.loads(tool_result)
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("status") == "pending_approval":
        value = data.get("action_id")
        return value if isinstance(value, str) else None
    return None


def _store(request: Request) -> ConversationStore:
    state = request.app.state
    store: ConversationStore | None = getattr(state, "conversations", None)
    if store is None:
        store = ConversationStore(state.db, state.cipher)
        state.conversations = store
    return store


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> ConversationPage:
    return _store(request).page(limit, cursor, q)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    found = _store(request).detail(conversation_id)
    if found is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return found


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str, body: RenameBody, request: Request
) -> ConversationSummary:
    try:
        renamed = _store(request).rename(conversation_id, body.title)
    except ValueError:
        raise HTTPException(status_code=422, detail="empty title") from None
    if renamed is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return renamed


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, request: Request) -> None:
    # Wait for a running turn of this conversation so it cannot persist into a deleted row.
    with request.app.state.chat_locks.hold(conversation_id):
        if not _store(request).delete(conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
