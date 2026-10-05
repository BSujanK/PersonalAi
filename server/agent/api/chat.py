"""POST /chat: runs the agent loop and persists the conversation encrypted."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent.core.llm import ChatMessage, LLMUnavailable, MissingApiKeyError, ToolCall
from agent.core.redact import RedactionMap, from_model
from agent.store.crypto import FieldCipher
from agent.store.db import Database

router = APIRouter()


class ChatRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    pending_action_ids: list[str]


def _encode(msg: ChatMessage) -> str:
    return json.dumps(
        {
            "content": msg.content.text,
            "tool_call_id": msg.tool_call_id,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments.text} for c in msg.tool_calls
            ]
            if msg.tool_calls
            else None,
        },
        ensure_ascii=False,
    )


def _decode(role: str, text: str) -> ChatMessage:
    data: dict[str, Any] = json.loads(text)
    calls = data["tool_calls"]
    return ChatMessage(
        role=role,  # type: ignore[arg-type]
        content=from_model(data["content"]),  # stored text is already placeholder space
        tool_call_id=data["tool_call_id"],
        tool_calls=[ToolCall(c["id"], c["name"], from_model(c["arguments"])) for c in calls]
        if calls
        else None,
    )


def _load_history(
    db: Database, cipher: FieldCipher, conversation_id: str
) -> tuple[list[ChatMessage], RedactionMap] | None:
    rows = db.query("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if not rows:
        return None
    blob = rows[0]["redaction_map_enc"]
    rmap = (
        RedactionMap.from_json(
            cipher.decrypt_str(blob, f"conversations.redaction_map:{conversation_id}")
        )
        if blob
        else RedactionMap()
    )
    history = [
        _decode(
            r["role"],
            cipher.decrypt_str(r["content_enc"], f"messages.content:{r['id']}"),
        )
        for r in db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq", (conversation_id,)
        )
    ]
    return history, rmap


def _run_turn(state: Any, body: ChatRequest, conversation_id: str, *, is_new: bool) -> ChatResponse:
    """Load history, run the loop and persist. The caller holds the conversation lock."""
    db: Database = state.db
    cipher: FieldCipher = state.cipher
    if is_new:
        history: list[ChatMessage] = []
        rmap = RedactionMap()
    else:
        loaded = _load_history(db, cipher, conversation_id)
        if loaded is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        history, rmap = loaded
    try:
        result = state.loop.run(conversation_id, history, body.message, rmap)
    except LLMUnavailable:
        raise HTTPException(status_code=503, detail="llm unavailable") from None
    except MissingApiKeyError:
        raise HTTPException(status_code=503, detail="llm not configured") from None
    now = state.clock().isoformat()
    with db.transaction():
        if is_new:
            db.execute(
                "INSERT INTO conversations (id, created_at) VALUES (?, ?)", (conversation_id, now)
            )
        db.execute(
            "UPDATE conversations SET redaction_map_enc = ? WHERE id = ?",
            (
                cipher.encrypt(rmap.to_json(), f"conversations.redaction_map:{conversation_id}"),
                conversation_id,
            ),
        )
        seq = len(history)
        for msg in result.new_messages:
            seq += 1
            message_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO messages (id, conversation_id, seq, created_at, role, content_enc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    seq,
                    now,
                    msg.role,
                    cipher.encrypt(_encode(msg), f"messages.content:{message_id}"),
                ),
            )
    return ChatResponse(
        conversation_id=conversation_id,
        reply=result.reply,
        pending_action_ids=result.pending_action_ids,
    )


@router.post("/chat")
def chat(body: ChatRequest, request: Request) -> ChatResponse:
    state = request.app.state
    is_new = body.conversation_id is None
    conversation_id = uuid.uuid4().hex if body.conversation_id is None else body.conversation_id
    # Turns of one conversation are serialised so seq numbers and history never interleave.
    with state.chat_locks.hold(conversation_id):
        return _run_turn(state, body, conversation_id, is_new=is_new)
