"""POST /chat: runs the agent loop and persists the conversation encrypted."""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.core.llm import ChatMessage, LLMNotConfigured, LLMUnavailable, ToolCall
from agent.core.redact import RedactionMap, from_model
from agent.store.crypto import FieldCipher
from agent.store.db import Database

log = logging.getLogger(__name__)
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


class _UnknownConversation(Exception):
    pass


def _execute_turn(
    state: Any,
    body: ChatRequest,
    conversation_id: str,
    *,
    is_new: bool,
    on_text: Callable[[str], None] | None = None,
    on_reset: Callable[[], None] | None = None,
) -> ChatResponse:
    """Load history, run the loop and persist. The caller holds the conversation lock."""
    db: Database = state.db
    cipher: FieldCipher = state.cipher
    if is_new:
        history: list[ChatMessage] = []
        rmap = RedactionMap()
    else:
        loaded = _load_history(db, cipher, conversation_id)
        if loaded is None:
            raise _UnknownConversation
        history, rmap = loaded
    result = state.loop.run(
        conversation_id, history, body.message, rmap, on_text=on_text, on_reset=on_reset
    )
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


def _run_turn(state: Any, body: ChatRequest, conversation_id: str, *, is_new: bool) -> ChatResponse:
    """JSON path of ``_execute_turn``. The caller holds the conversation lock."""
    try:
        return _execute_turn(state, body, conversation_id, is_new=is_new)
    except _UnknownConversation:
        raise HTTPException(status_code=404, detail="conversation not found") from None
    except LLMUnavailable:
        raise HTTPException(status_code=503, detail="llm unavailable") from None
    except LLMNotConfigured:
        raise HTTPException(status_code=503, detail="llm not configured") from None


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _stream_turn(
    state: Any, body: ChatRequest, conversation_id: str, *, is_new: bool
) -> StreamingResponse:
    """Run the turn in a worker thread that holds the conversation lock until it has persisted.

    The worker finishes and persists even if the client disconnects mid-stream.
    """
    events: queue.Queue[bytes | None] = queue.Queue()

    def work() -> None:
        try:
            with state.chat_locks.hold(conversation_id):
                response = _execute_turn(
                    state,
                    body,
                    conversation_id,
                    is_new=is_new,
                    on_text=lambda text: events.put(_sse("token", {"text": text})),
                    on_reset=lambda: events.put(_sse("reset", {})),
                )
            events.put(_sse("done", response.model_dump()))
        except LLMUnavailable:
            events.put(_sse("error", {"detail": "llm unavailable"}))
        except LLMNotConfigured:
            events.put(_sse("error", {"detail": "llm not configured"}))
        except Exception as exc:  # the client gets no exception text; type is enough to debug
            log.error("chat stream failed: %s", type(exc).__name__)
            events.put(_sse("error", {"detail": "internal error"}))
        finally:
            events.put(None)

    threading.Thread(target=work, name="chat-stream", daemon=True).start()

    def generate() -> Iterator[bytes]:
        yield _sse("start", {"conversation_id": conversation_id})
        while (item := events.get()) is not None:
            yield item

    return StreamingResponse(
        generate(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, request: Request) -> ChatResponse | StreamingResponse:
    state = request.app.state
    is_new = body.conversation_id is None
    conversation_id = uuid.uuid4().hex if body.conversation_id is None else body.conversation_id
    if "text/event-stream" in request.headers.get("accept", "").lower():
        if not is_new and not state.db.query(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ):
            raise HTTPException(status_code=404, detail="conversation not found")
        return _stream_turn(state, body, conversation_id, is_new=is_new)
    # Turns of one conversation are serialised so seq numbers and history never interleave.
    with state.chat_locks.hold(conversation_id):
        return _run_turn(state, body, conversation_id, is_new=is_new)
