"""The current conversation turn, so a tool can scope state to one owner message.

``AgentLoop.run`` opens a scope for each turn. A tool reads ``current_turn()`` to keep per-turn
state (for example the URLs ``web_search`` returned, which are the only ones ``web_read`` may
fetch). Outside a turn it is ``None``, and such tools must refuse.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_current: ContextVar[str | None] = ContextVar("personalai_turn", default=None)


def current_turn() -> str | None:
    return _current.get()


@contextmanager
def turn_scope() -> Iterator[str]:
    """A fresh, unguessable turn id for the duration of the block."""
    turn_id = secrets.token_hex(16)
    token = _current.set(turn_id)
    try:
        yield turn_id
    finally:
        _current.reset(token)
