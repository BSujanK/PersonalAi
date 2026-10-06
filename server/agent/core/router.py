"""Local tool router: chooses which tool schemas the model is shown for one request.

Sending every schema on every call makes replies slow and costs tokens, so the router narrows
the list from keywords in the owner's own message. It only decides what the model *sees*:

- It never changes a tool's READ/WRITE registration, so a WRITE tool is still only ever a
  ``PendingAction`` (CLAUDE.md rule 1), and it adds no execution path of its own.
- Its inputs are the owner's message, the tool names of the conversation's recent turns and the
  registered names. Mail, file, SMS and news text returned by tools never reaches it
  (CLAUDE.md rule 4).
- When nothing matches, every tool is offered, so the model is never stranded.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

# Cheap READ tools that answer "what is going on" questions, offered with every routed request.
GENERAL_TOOLS = ("mail_digest", "account_overview", "calendar_events")


@dataclass(frozen=True)
class ToolGroup:
    """An intent: keywords in the message, and the tools (by exact name or prefix) it unlocks."""

    name: str
    keywords: re.Pattern[str]
    names: frozenset[str] = frozenset()
    prefixes: tuple[str, ...] = ()

    def tools_in(self, registry_names: Iterable[str]) -> set[str]:
        return {n for n in registry_names if n in self.names or n.startswith(self.prefixes)}


def _words(*alternatives: str) -> re.Pattern[str]:
    """Case-insensitive, word-bounded match of any alternative (regex fragments)."""
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


GROUPS: tuple[ToolGroup, ...] = (
    ToolGroup(
        "mail",
        _words(
            r"e-?mails?",
            r"mails?",
            r"gmail",
            r"inbox",
            r"unread",
            r"repl(?:y|ies|ied|ying)",
            r"respon(?:d|ded|ding|se)",
            r"send(?:ing)?",
            r"sent",
            r"forward(?:ed|ing)?",
            r"messages?",
            r"sender",
            r"archive",
            r"trash",
            r"labels?",
            r"attach(?:ed|ment|ments)?",
        ),
        prefixes=("mail_",),
    ),
    ToolGroup(
        "calendar",
        _words(
            r"calendars?",
            r"events?",
            r"meetings?",
            r"schedul\w*",
            r"appointments?",
            r"agenda",
            r"remind\w*",
            r"alarms?",
            r"timers?",
            r"invite[ds]?",
        ),
        prefixes=("calendar_", "phone_"),
    ),
    ToolGroup(
        "deadlines",
        _words(
            r"deadlines?",
            r"due",
            r"assignments?",
            r"homework",
            r"exams?",
            r"quiz(?:zes)?",
            r"submi\w+",
            r"classroom",
            r"courses?",
            r"class(?:es)?",
            r"lectures?",
            r"coursework",
            r"announcements?",
        ),
        # Due dates often live in mail, so the mail readers come along.
        names=frozenset({"calendar_add_deadline", "mail_search", "mail_read"}),
        prefixes=("classroom_",),
    ),
    ToolGroup(
        "finance",
        _words(
            r"money",
            r"spen[dt]\w*",
            r"expenses?",
            r"balances?",
            r"accounts?",
            r"transactions?",
            r"upi",
            r"bank\w*",
            r"salary",
            r"paid",
            r"pay(?:ment|ments|ing)?",
            r"credit(?:ed)?",
            r"debit(?:ed)?",
            r"rupees?",
            r"inr",
            r"rs",
            r"cash",
            r"budget",
        ),
        names=frozenset({"spend_summary", "balances", "transactions", "account_overview"}),
    ),
    ToolGroup(
        "files",
        _words(
            r"files?",
            r"folders?",
            r"drive",
            r"documents?",
            r"docs?",
            r"pdfs?",
            r"share[ds]?",
            r"sharing",
            r"upload\w*",
            r"download\w*",
            r"sheets?",
            r"slides?",
            r"notes?",
        ),
        prefixes=("files_", "drive_"),
    ),
    ToolGroup(
        "news",
        _words(r"news", r"headlines?", r"articles?"),
        names=frozenset({"news_headlines"}),
    ),
)


def select_tools(
    message: str,
    recent_tool_names: Sequence[str],
    registry_names: Collection[str],
) -> list[str]:
    """Names of the tools to offer for ``message``, in registry order.

    The result is the union of the groups the message matches, the tools used in recent turns
    and a few general tools. If no group matches (or none has a registered tool), it is every
    registered tool. Pure and deterministic.
    """
    matched: set[str] = set()
    for group in GROUPS:
        if group.keywords.search(message):
            matched |= group.tools_in(registry_names)
    ordered = registry_names if isinstance(registry_names, Sequence) else sorted(registry_names)
    if not matched:
        return list(ordered)
    chosen = matched | set(GENERAL_TOOLS) | set(recent_tool_names)
    return [name for name in ordered if name in chosen]
