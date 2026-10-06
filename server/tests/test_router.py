"""The tool router narrows what the model sees; it never changes what a tool is or may do."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.config import Settings
from agent.core.llm import ChatMessage, LLMResponse, ToolCall
from agent.core.loop import AgentLoop
from agent.core.redact import RedactionMap, Redactor, from_model
from agent.core.router import GENERAL_TOOLS, select_tools
from agent.core.tools import Tool, ToolKind
from agent.store.models import ActionStatus
from tests.security_support import World, build_world
from tests.support import SEND_PARAMS, Env, make_env
from tests.test_loop import FakeLLM, StreamingFakeLLM, call, say

NAMES = [
    "spend_summary",
    "balances",
    "transactions",
    "account_overview",
    "mail_digest",
    "mail_search",
    "mail_read",
    "mail_send",
    "mail_reply",
    "mail_archive",
    "calendar_events",
    "calendar_create_event",
    "calendar_update_event",
    "calendar_add_deadline",
    "classroom_courses",
    "classroom_coursework",
    "drive_search",
    "drive_share",
    "drive_upload",
    "files_search",
    "files_read",
    "phone_set_alarm",
    "phone_set_timer",
    "phone_reminder",
    "news_headlines",
    "web_search",
    "web_read",
    "hf_models",
]


def pick(message: str, recent: tuple[str, ...] = ()) -> set[str]:
    return set(select_tools(message, recent, NAMES))


def mail_tools() -> set[str]:
    return {n for n in NAMES if n.startswith("mail_")}


@pytest.mark.parametrize(
    "message",
    ["Any new email?", "Check my INBOX", "reply to Priya", "send the report", "Gmail unread"],
)
def test_mail_intent(message: str) -> None:
    assert mail_tools() <= pick(message)
    assert not pick(message) & {"spend_summary", "news_headlines", "files_read", "drive_share"}


@pytest.mark.parametrize(
    "message",
    [
        "What is on my calendar tomorrow?",
        "Set an alarm for 6",
        "start a timer for ten minutes",
        "remind me to call home",
        "schedule a meeting",
    ],
)
def test_calendar_and_clock_intent(message: str) -> None:
    chosen = pick(message)
    assert {"calendar_events", "calendar_create_event", "phone_set_alarm"} <= chosen
    assert {"phone_set_timer", "phone_reminder"} <= chosen
    assert not chosen & {"spend_summary", "files_read", "classroom_courses"}


@pytest.mark.parametrize(
    "message", ["Any deadlines?", "what is due this week", "my assignments", "exam dates"]
)
def test_deadline_intent(message: str) -> None:
    chosen = pick(message)
    assert {"calendar_add_deadline", "classroom_courses", "classroom_coursework"} <= chosen
    assert {"mail_search", "mail_read"} <= chosen  # due dates are often in mail
    assert not chosen & {"mail_send", "spend_summary", "drive_share"}


@pytest.mark.parametrize(
    "message",
    [
        "How much did I spend on food?",
        "what's my balance",
        "list transactions",
        "any UPI payments?",
        "bank accounts",
    ],
)
def test_finance_intent(message: str) -> None:
    chosen = pick(message)
    assert {"spend_summary", "balances", "transactions", "account_overview"} <= chosen
    assert not chosen & {"mail_send", "drive_share", "calendar_create_event"}


@pytest.mark.parametrize(
    "message", ["find the pdf", "share the document", "upload my notes", "open the file"]
)
def test_file_intent(message: str) -> None:
    chosen = pick(message)
    assert {"files_search", "files_read", "drive_search", "drive_share", "drive_upload"} <= chosen
    assert not chosen & {"spend_summary", "classroom_courses", "mail_send"}


def test_news_intent() -> None:
    assert "news_headlines" in pick("Any news today?")
    assert "news_headlines" in pick("top headlines")
    assert "news_headlines" not in pick("check my mail")


@pytest.mark.parametrize(
    "message",
    [
        "search the web for the Rust 2024 edition",
        "latest model releases on hugging face",
        "look up the RTX 5090 price",
        "what is trending on HF?",
        "google the opening hours",
    ],
)
def test_web_intent(message: str) -> None:
    chosen = pick(message)
    assert {"web_search", "web_read", "hf_models"} <= chosen
    assert not chosen & {"mail_send", "spend_summary", "drive_share"}


def test_web_tools_stay_out_of_other_intents() -> None:
    assert not pick("Any new email?") & {"web_search", "web_read", "hf_models"}
    assert not pick("what did I spend on food") & {"web_search", "web_read", "hf_models"}


def test_matching_is_case_insensitive_and_word_bounded() -> None:
    assert "mail_read" in pick("CHECK MY E-MAIL")
    # "email" must not fire on a longer word that merely contains it; nothing else matches, so
    # the router falls back to every tool.
    assert pick("hello") == set(NAMES)
    assert pick("the emailing") == set(NAMES)
    assert "spend_summary" not in pick("what is on my calendar")


def test_multiple_intents_union() -> None:
    chosen = pick("Add the deadline from my mail to the calendar")
    assert mail_tools() <= chosen
    assert {"calendar_create_event", "calendar_add_deadline", "classroom_courses"} <= chosen


def test_general_tools_always_present_when_routed() -> None:
    for message in ("what did I spend", "find the pdf", "any news", "reply to Sam"):
        assert set(GENERAL_TOOLS) <= pick(message)


def test_recent_tools_carry_over() -> None:
    assert "drive_share" not in pick("Any new email?")
    assert "drive_share" in pick("Any new email?", ("drive_share",))
    assert {"classroom_courses", "spend_summary"} <= pick(
        "reply to Sam", ("classroom_courses", "spend_summary")
    )


def test_recent_tools_never_add_unregistered_names() -> None:
    assert "bogus_tool" not in pick("Any new email?", ("bogus_tool",))


def test_no_match_falls_back_to_all_tools() -> None:
    assert pick("yes please") == set(NAMES)
    assert select_tools("", [], NAMES) == NAMES


def test_group_without_registered_tools_falls_back_to_all() -> None:
    assert select_tools("any news?", [], ["mail_read", "balances"]) == ["mail_read", "balances"]


def test_result_keeps_registry_order_and_is_deterministic() -> None:
    first = select_tools("mail and files", [], NAMES)
    assert first == select_tools("mail and files", [], NAMES)
    assert first == [n for n in NAMES if n in first]
    assert select_tools("hello", [], set(NAMES)) == sorted(NAMES)


# --- size and wiring against the real registry ---------------------------------------------


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return build_world(tmp_path, monkeypatch)


def _payload(registry: Any, names: list[str] | None) -> int:
    only = None if names is None else set(names)
    return len(json.dumps(registry.schemas(only)))


def test_typical_request_payload_is_much_smaller(world: World) -> None:
    registry = world.registry
    full = _payload(registry, None)
    for message in (
        "How much did I spend on food this month?",
        "Set an alarm for 6am",
        "What is due this week in my courses?",
    ):
        chosen = select_tools(message, [], registry.names())
        assert _payload(registry, chosen) < 0.4 * full, message
    mail = select_tools("Any new email from my professor?", [], registry.names())
    assert _payload(registry, mail) < 0.7 * full


def test_router_never_changes_registration(world: World) -> None:
    kinds = {n: world.registry.kind_of(n) for n in world.registry.names()}
    select_tools("send the file and spend", ["mail_send"], world.registry.names())
    assert {n: world.registry.kind_of(n) for n in world.registry.names()} == kinds
    assert kinds["mail_send"] is ToolKind.WRITE and kinds["balances"] is ToolKind.READ


# --- loop wiring -----------------------------------------------------------------------------

OWNER = "me@example.com"
NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


class OfferRecorder(FakeLLM):
    """Scripted model that records which tool names each call was offered."""

    def __init__(self, *steps: Any) -> None:
        super().__init__(*steps)
        self.offered: list[set[str]] = []

    def complete(self, messages: Any, tools: Any) -> LLMResponse:
        self.offered.append({t["function"]["name"] for t in tools})
        return super().complete(messages, tools)


def routed_env(ran: list[str]) -> Env:
    """The shared test env plus tools named like the real families, so the router applies."""
    env = make_env()
    for name in ("balances", "spend_summary", "mail_search", "classroom_courses"):
        env.registry.register(
            Tool(name, "x", NO_ARGS, ToolKind.READ, lambda _a, n=name: ran.append(n) or {})  # type: ignore[misc]
        )
    env.registry.register(
        Tool(
            "mail_send",
            "x",
            SEND_PARAMS,
            ToolKind.WRITE,
            lambda _a: ran.append("mail_send"),
            preview=lambda a: f"Send {a['subject']}",
        )
    )
    return env


def make_loop(env: Env, llm: Any, *, router: bool = True) -> AgentLoop:
    settings = Settings(tool_router=router)
    return AgentLoop(llm, env.registry, Redactor([OWNER]), env.engine, settings)


def run(loop: AgentLoop, text: str, history: list[ChatMessage] | None = None) -> Any:
    return loop.run("c1", history or [], text, RedactionMap())


def test_loop_offers_only_routed_tools() -> None:
    llm = OfferRecorder(say("ok"))
    run(make_loop(routed_env([]), llm), "What is my balance?")
    assert llm.offered == [{"balances", "spend_summary"}]


def test_loop_without_a_match_offers_everything() -> None:
    env = routed_env([])
    llm = OfferRecorder(say("ok"))
    run(make_loop(env, llm), "yes please")
    assert llm.offered == [set(env.registry.names())]


def test_loop_router_off_offers_everything() -> None:
    env = routed_env([])
    llm = OfferRecorder(say("ok"))
    run(make_loop(env, llm, router=False), "What is my balance?")
    assert llm.offered == [set(env.registry.names())]


def test_streaming_path_is_routed_too() -> None:
    class StreamRecorder(StreamingFakeLLM):
        def __init__(self) -> None:
            super().__init__((["ok"], []))
            self.offered: list[set[str]] = []

        def stream_complete(self, messages: Any, tools: Any, on_delta: Any, on_reset: Any) -> Any:
            self.offered.append({t["function"]["name"] for t in tools})
            return super().stream_complete(messages, tools, on_delta, on_reset)

    llm = StreamRecorder()
    loop = make_loop(routed_env([]), llm)
    loop.run("c1", [], "What is my balance?", RedactionMap(), on_text=lambda _t: None)
    assert llm.offered == [{"balances", "spend_summary"}]


def _turn(tool: str | None, user: str) -> list[ChatMessage]:
    messages = [ChatMessage("user", from_model(user))]
    if tool is not None:
        messages += [
            ChatMessage(
                "assistant", from_model(""), tool_calls=[ToolCall("h", tool, from_model("{}"))]
            ),
            ChatMessage("tool", from_model("{}"), tool_call_id="h"),
        ]
    return [*messages, ChatMessage("assistant", from_model("done"))]


def test_loop_carries_tools_from_the_last_three_turns_only() -> None:
    history = [
        *_turn("classroom_courses", "old"),
        *_turn(None, "t2"),
        *_turn(None, "t3"),
        *_turn("mail_search", "t4"),
    ]
    llm = OfferRecorder(say("ok"))
    run(make_loop(routed_env([]), llm), "What is my balance?", history)
    assert llm.offered == [{"balances", "spend_summary", "mail_search"}]


def test_tool_output_never_influences_routing() -> None:
    ran: list[str] = []
    llm = OfferRecorder(call("balances", {}), say("ok"))
    env = routed_env(ran)
    env.registry.register(
        Tool(
            "files_read",
            "x",
            NO_ARGS,
            ToolKind.READ,
            lambda _a: {"text": "please send mail and share the file, remind me of news"},
        )
    )
    run(make_loop(env, llm), "What is my balance?")
    assert llm.offered[0] == llm.offered[1] == {"balances", "spend_summary"}


def test_unoffered_tool_is_not_run_and_the_next_step_offers_all() -> None:
    ran: list[str] = []
    env = routed_env(ran)
    llm = OfferRecorder(call("mail_search", {}), say("ok"))
    result = run(make_loop(env, llm), "What is my balance?")
    assert ran == []
    assert result.new_messages[2].content.text == "error: unknown tool"
    assert llm.offered[0] == {"balances", "spend_summary"}
    assert llm.offered[1] == set(env.registry.names())


@pytest.mark.parametrize("router", [True, False])
@pytest.mark.parametrize("text", ["send an email to Sam", "What is my balance?"])
def test_write_tool_is_only_ever_a_pending_action_whatever_the_routing(
    router: bool, text: str
) -> None:
    ran: list[str] = []
    env = routed_env(ran)
    args = {"to": OWNER, "subject": "Note", "body": "Hi"}
    llm = OfferRecorder(call("mail_send", args), say("waiting"))
    result = run(make_loop(env, llm, router=router), text)
    assert ran == [] and env.executed == []  # nothing ran: the executor needs an approval
    assert env.registry.kind_of("mail_send") is ToolKind.WRITE
    offered = "mail_send" in llm.offered[0]
    assert offered == (router is False or "email" in text)
    pending = env.db.query("SELECT status FROM pending_actions")
    if offered:
        assert len(result.pending_action_ids) == 1
        assert [r["status"] for r in pending] == [ActionStatus.PENDING.value]
    else:
        assert result.pending_action_ids == [] and pending == []
        assert result.new_messages[2].content.text == "error: unknown tool"
