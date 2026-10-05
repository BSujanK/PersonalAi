"""Tool registry. READ/WRITE is fixed at registration; WRITE executors never run from here."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent.core.policy import FORBIDDEN_TOOL_PATTERNS

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ToolKind(StrEnum):
    READ = "read"
    WRITE = "write"


class ForbiddenToolError(ValueError):
    """Tool name matches a forbidden pattern (e.g. broker order APIs)."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    kind: ToolKind
    # READ: the reader. WRITE: the executor, invoked only by ApprovalEngine after approval.
    run: Callable[[dict[str, Any]], Any]
    preview: Callable[[dict[str, Any]], str] | None = None
    untrusted_output: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not _NAME_RE.fullmatch(tool.name):
            raise ValueError(f"invalid tool name: {tool.name!r}")
        if any(p.search(tool.name) for p in FORBIDDEN_TOOL_PATTERNS):
            raise ForbiddenToolError(f"forbidden tool name: {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name!r}")
        if tool.kind is ToolKind.WRITE and tool.preview is None:
            raise ValueError("WRITE tools require a preview")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def kind_of(self, name: str) -> ToolKind | None:
        tool = self._tools.get(name)
        return tool.kind if tool else None

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def executor_for_approved(self, name: str) -> Callable[[dict[str, Any]], Any]:
        """Return a WRITE tool's executor.

        Must only be called from ``agent.core.approvals`` after a verified approval. There is
        deliberately no registry method that runs a WRITE directly.
        """
        tool = self._tools.get(name)
        if tool is None or tool.kind is not ToolKind.WRITE:
            raise KeyError(name)
        return tool.run
