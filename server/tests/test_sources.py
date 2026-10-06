"""Web sources under an answer: collected from raw web-tool results, never from model text."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.config import Settings
from agent.core.loop import AgentLoop
from agent.core.redact import RedactionMap, Redactor
from agent.core.sources import MAX_SOURCES, TITLE_MAX, SourceCollector
from agent.core.tools import Tool, ToolKind
from agent.store.db import Database
from agent.store.keystore import KeyStore
from tests.support import Env, FakeClock, make_env, make_registry
from tests.test_api import Api, _auth, _mail_services, _pair
from tests.test_chat_stream import _stream
from tests.test_loop import OWNER, FakeLLM, call, say

QUESTION = "search the web for news"
OPEN_OBJECT: dict[str, Any] = {"type": "object", "additionalProperties": True}


def _search(*items: tuple[str, str]) -> dict[str, Any]:
    return {
        "results": [
            {"id": f"w{i}", "title": title, "url": url, "snippet": "text"}
            for i, (title, url) in enumerate(items, 1)
        ]
    }


def _page(url: str, title: str = "A page") -> dict[str, Any]:
    return {"url": url, "final_url": url, "title": title, "text": "body", "truncated": False}


def _models(*ids: str) -> dict[str, Any]:
    return {"models": [{"id": i, "url": f"https://huggingface.co/{i}"} for i in ids]}


def _register(env: Env, results: dict[str, Any]) -> None:
    for name, result in results.items():
        env.registry.register(
            Tool(
                name=name,
                description=f"fake {name}",
                parameters=OPEN_OBJECT,
                kind=ToolKind.READ,
                run=lambda _args, result=result: result,
                untrusted_output=True,
                rehydrate_args=False,
            )
        )


def _run(results: dict[str, Any], *steps: Any, text: str = QUESTION) -> Any:
    env = make_env()
    _register(env, results)
    llm = FakeLLM(*steps, say("done"))
    loop = AgentLoop(llm, env.registry, Redactor([OWNER]), env.engine, Settings())
    return loop.run("c1", [], text, RedactionMap())


def _pairs(sources: list[Any]) -> list[tuple[str, str]]:
    return [(s.title, s.url) for s in sources]


# -- collector -------------------------------------------------------------------------------


def test_sources_from_web_search_results() -> None:
    result = _run(
        {
            "web_search": _search(
                ("First", "https://a.example.com/x"), ("Second", "http://b.example.com")
            )
        },
        call("web_search", {"query": "news"}),
    )
    assert _pairs(result.sources) == [
        ("First", "https://a.example.com/x"),
        ("Second", "http://b.example.com"),
    ]


def test_sources_from_web_read_use_the_page_title() -> None:
    result = _run(
        {"web_read": _page("https://a.example.com/post", "The post")},
        call("web_read", {"url": "w1"}),
    )
    assert _pairs(result.sources) == [("The post", "https://a.example.com/post")]


def test_sources_from_hf_models_use_the_model_id_as_title() -> None:
    result = _run(
        {"hf_models": _models("acme/tiny", "acme/big")},
        call("hf_models", {}),
    )
    assert _pairs(result.sources) == [
        ("acme/tiny", "https://huggingface.co/acme/tiny"),
        ("acme/big", "https://huggingface.co/acme/big"),
    ]


def test_no_sources_when_no_web_tool_ran() -> None:
    assert _run({}, call("read_mail", {})).sources == []
    assert _run({}).sources == []


def test_a_failed_web_tool_gives_no_sources() -> None:
    result = _run(
        {"web_read": {"error": "the page could not be read", "url": "https://a.example.com"}},
        call("web_read", {"url": "w1"}),
    )
    assert result.sources == []


def test_model_text_never_becomes_a_source() -> None:
    result = _run({}, say("See https://invented.example.com for more."))
    assert result.sources == []


def test_priority_is_pages_then_search_then_models() -> None:
    result = _run(
        {
            "web_search": _search(
                ("S1", "https://s1.example.com"), ("S2", "https://s2.example.com")
            ),
            "web_read": _page("https://p.example.com", "P"),
            "hf_models": _models("acme/m"),
        },
        call("hf_models", {}, "c1"),
        call("web_search", {"query": "news"}, "c2"),
        call("web_read", {"url": "w1"}, "c3"),
    )
    assert [s.url for s in result.sources] == [
        "https://p.example.com",
        "https://s1.example.com",
        "https://s2.example.com",
        "https://huggingface.co/acme/m",
    ]


def test_duplicates_are_removed_by_url_without_fragment() -> None:
    result = _run(
        {
            "web_search": _search(
                ("Search title", "https://a.example.com/x#top"),
                ("Other", "https://b.example.com"),
                ("Again", "https://b.example.com#frag"),
            ),
            "web_read": _page("https://a.example.com/x#intro", "Read title"),
        },
        call("web_search", {"query": "news"}, "c1"),
        call("web_read", {"url": "w1"}, "c2"),
    )
    assert _pairs(result.sources) == [
        ("Read title", "https://a.example.com/x"),
        ("Other", "https://b.example.com"),
    ]


def test_at_most_five_sources() -> None:
    items = [(f"T{i}", f"https://h{i}.example.com") for i in range(8)]
    result = _run({"web_search": _search(*items)}, call("web_search", {"query": "news"}))
    assert len(result.sources) == MAX_SOURCES == 5
    assert [s.title for s in result.sources] == ["T0", "T1", "T2", "T3", "T4"]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://files.example.com/a",
        "file:///etc/passwd",
        "data:text/html,hi",
        "https://",
        "https:///path",
        "/relative/path",
        "https://user:pw@host.example.com/",
        "https://host.example.com/a b",
        "https://host.example.com/\nx",
        "https://host.example.com/" + "a" * 2000,
        "",
        None,
        42,
    ],
)
def test_unsafe_or_malformed_urls_are_dropped(url: object) -> None:
    collector = SourceCollector()
    collector.add("web_search", {"results": [{"title": "Bad", "url": url}]})
    collector.add("web_read", {"url": url, "title": "Bad"})
    collector.add("hf_models", {"models": [{"id": "x/y", "url": url}]})
    assert collector.top() == []


def test_titles_are_single_line_clean_and_capped() -> None:
    long_title = "word " * 100
    collector = SourceCollector()
    collector.add(
        "web_search",
        {
            "results": [
                {
                    "title": "Line one\n\tline" + chr(0x202E) + "two" + chr(0x200B) + "  end",
                    "url": "https://a.example.com",
                },
                {"title": long_title, "url": "https://b.example.com"},
                {"title": "   ", "url": "https://c.example.com/page"},
                {"title": None, "url": "https://d.example.com"},
            ]
        },
    )
    titles = [s.title for s in collector.top()]
    assert titles[0] == "Line one linetwo end"
    assert len(titles[1]) <= TITLE_MAX and "\n" not in titles[1]
    assert titles[2:] == ["c.example.com", "d.example.com"]


def test_other_tools_and_odd_results_are_ignored() -> None:
    collector = SourceCollector()
    collector.add("read_mail", {"url": "https://a.example.com", "title": "x"})
    collector.add("web_search", "not a dict")
    collector.add("web_search", {"results": "nope"})
    collector.add("web_search", {"results": ["nope", 3, {"url": "https://ok.example.com"}]})
    assert [s.url for s in collector.top()] == ["https://ok.example.com"]


def test_sources_are_collected_over_several_steps_of_one_turn_only() -> None:
    env = make_env()
    _register(env, {"web_search": _search(("One", "https://one.example.com"))})
    loop = AgentLoop(
        FakeLLM(call("web_search", {"query": "news"}), say("ok")),
        env.registry,
        Redactor([OWNER]),
        env.engine,
        Settings(),
    )
    first = loop.run("c1", [], QUESTION, RedactionMap())
    second = loop.run("c1", [], "thanks", RedactionMap())
    assert len(first.sources) == 1
    assert second.sources == []


def test_sources_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        _run(
            {"web_search": _search(("SecretTitleXyz", "https://secret-host.example.com/p"))},
            call("web_search", {"query": "news"}),
        )
    assert "SecretTitleXyz" not in caplog.text
    assert "secret-host" not in caplog.text


# -- API: /chat JSON, SSE done event and conversation detail -----------------------------------


def _web_api(llm: FakeLLM, results: dict[str, Any]) -> Api:
    db = Database(":memory:")
    clock = FakeClock()
    keystore = KeyStore()
    executed: list[dict[str, Any]] = []
    registry = make_registry(executed)
    for name, result in results.items():
        registry.register(
            Tool(
                name=name,
                description=f"fake {name}",
                parameters=OPEN_OBJECT,
                kind=ToolKind.READ,
                run=lambda _args, result=result: result,
                untrusted_output=True,
                rehydrate_args=False,
            )
        )
    app = create_app(
        Settings(owner_emails=(OWNER,)),
        db=db,
        keystore=keystore,
        llm=llm,
        registry=registry,
        clock=clock,
        mail=_mail_services(db, clock, keystore),
    )
    return Api(app, TestClient(app), db, clock, executed)


SEARCH = _search(("First", "https://a.example.com/x"), ("Second", "https://b.example.com"))
EXPECTED = [
    {"title": "First", "url": "https://a.example.com/x"},
    {"title": "Second", "url": "https://b.example.com"},
]


def test_chat_json_carries_sources() -> None:
    api = _web_api(
        FakeLLM(call("web_search", {"query": "news"}), say("Here.")), {"web_search": SEARCH}
    )
    resp = api.client.post("/chat", headers=_auth(_pair(api)), json={"message": QUESTION})
    assert resp.status_code == 200
    assert resp.json()["sources"] == EXPECTED


def test_chat_json_without_web_tools_has_empty_sources() -> None:
    api = _web_api(FakeLLM(say("hello")), {})
    resp = api.client.post("/chat", headers=_auth(_pair(api)), json={"message": "hi"})
    assert resp.json()["sources"] == []


def test_sse_done_event_carries_sources() -> None:
    api = _web_api(
        FakeLLM(call("web_search", {"query": "news"}), say("Here.")), {"web_search": SEARCH}
    )
    events = _stream(api, _auth(_pair(api)), {"message": QUESTION})
    done = events[-1]
    assert done[0] == "done"
    assert done[1]["sources"] == EXPECTED
    assert "https://a.example.com" not in json.dumps(events[:-1])


def test_conversation_detail_returns_sources_on_the_assistant_turn_only() -> None:
    api = _web_api(
        FakeLLM(call("web_search", {"query": "news"}), say("Here.")), {"web_search": SEARCH}
    )
    headers = _auth(_pair(api))
    cid = api.client.post("/chat", headers=headers, json={"message": QUESTION}).json()[
        "conversation_id"
    ]
    messages = api.client.get(f"/conversations/{cid}", headers=headers).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0].get("sources", []) == []
    assert messages[1]["sources"] == EXPECTED


def test_sources_are_stored_encrypted_and_not_replayed_to_the_model() -> None:
    llm = FakeLLM(call("web_search", {"query": "news"}), say("Here."), say("Again."))
    api = _web_api(llm, {"web_search": SEARCH})
    headers = _auth(_pair(api))
    cid = api.client.post("/chat", headers=headers, json={"message": QUESTION}).json()[
        "conversation_id"
    ]
    for row in api.db.query("SELECT content_enc FROM messages"):
        assert b"b.example.com/" not in bytes(row["content_enc"])
        assert b"Second" not in bytes(row["content_enc"])
    api.client.post("/chat", headers=headers, json={"message": "and?", "conversation_id": cid})
    replayed = [m for m in llm.received[-1] if m.role == "assistant" and not m.tool_calls]
    assert replayed and all("sources" not in m.content.text for m in replayed)


def test_a_conversation_without_stored_sources_returns_an_empty_list() -> None:
    api = _web_api(FakeLLM(say("hello")), {})
    headers = _auth(_pair(api))
    cid = api.client.post("/chat", headers=headers, json={"message": "hi"}).json()[
        "conversation_id"
    ]
    messages = api.client.get(f"/conversations/{cid}", headers=headers).json()["messages"]
    assert messages[1]["sources"] == []
