from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent.config import Settings
from agent.core.llm import (
    ChatMessage,
    FallbackClient,
    LLMUnavailable,
    MissingApiKeyError,
    OpenAICompatClient,
    UnredactedPayloadError,
    build_default_client,
)
from agent.core.redact import RedactionMap, Redactor, from_model
from agent.store.keystore import KeyStore

Handler = Callable[[httpx.Request], httpx.Response]


def _completion(content: str | None = "hi", tool_calls: list[dict[str, Any]] | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def _client(handler: Handler, sleeps: list[float] | None = None, **kw: Any) -> OpenAICompatClient:
    record = sleeps if sleeps is not None else []
    return OpenAICompatClient(
        "http://127.0.0.1:9/v1",
        "key",
        "model",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=record.append,
        **kw,
    )


def _msgs(text: str) -> list[ChatMessage]:
    return [ChatMessage("user", Redactor().redact(text, RedactionMap()))]


def test_request_contains_placeholders_not_raw_pii() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion())

    rmap = RedactionMap()
    red = Redactor(["me@example.com"]).redact("card 4111111111111111 for me@example.com", rmap)
    reply = _client(handler).complete([ChatMessage("user", red)], [])
    body = json.dumps(seen[0])
    assert "4111111111111111" not in body and "me@example.com" not in body
    assert "CARD_1" in body
    assert reply.content is not None and reply.content.text == "hi"
    assert "tools" not in seen[0]


def test_rate_limit_then_success_retries_with_backoff() -> None:
    codes = iter([429, 200])
    sleeps: list[float] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        code = next(codes)
        return httpx.Response(code, json=_completion() if code == 200 else {"error": {}})

    out = _client(handler, sleeps).complete(_msgs("hello"), [])
    assert out.content is not None
    assert sleeps == [1.0]


def test_persistent_503_raises_after_backoff() -> None:
    sleeps: list[float] = []
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": {}})

    with pytest.raises(LLMUnavailable):
        _client(handler, sleeps).complete(_msgs("hello"), [])
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(calls) == 4


def test_connection_errors_are_retried() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(LLMUnavailable):
        _client(handler, sleeps, max_retries=2).complete(_msgs("hello"), [])
    assert sleeps == [1.0, 2.0]


def test_client_error_is_not_retried() -> None:
    sleeps: list[float] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {}})

    with pytest.raises(LLMUnavailable):
        _client(handler, sleeps).complete(_msgs("hello"), [])
    assert sleeps == []


def test_fallback_used_when_primary_unavailable() -> None:
    def down(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {}})

    def ok(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("from fallback"))

    client = FallbackClient(_client(down), _client(ok))
    out = client.complete(_msgs("hello"), [])
    assert out.content is not None and out.content.text == "from fallback"


def test_plain_str_content_is_refused_and_no_request_is_made() -> None:
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_completion())

    client = _client(handler)
    bad = ChatMessage("user", "raw 4111111111111111")  # type: ignore[arg-type]
    with pytest.raises(UnredactedPayloadError):
        client.complete([bad], [])
    assert calls == []


def test_unredacted_tool_call_arguments_are_refused() -> None:
    from agent.core.llm import ToolCall

    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_completion())

    msg = ChatMessage(
        "assistant",
        from_model(""),
        tool_calls=[ToolCall("1", "send_email", '{"to": "x"}')],  # type: ignore[arg-type]
    )
    with pytest.raises(UnredactedPayloadError):
        _client(handler).complete([msg], [])
    assert calls == []


def test_tool_calls_parsed_and_tools_sent() -> None:
    seen: list[dict[str, Any]] = []
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read_mail", "arguments": '{"q": "⟨ACCT_1⟩"}'},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion(None, [tool_call]))

    schema = {"type": "function", "function": {"name": "read_mail", "parameters": {}}}
    out = _client(handler).complete(_msgs("hello"), [schema])
    assert out.content is None
    assert [(c.id, c.name, c.arguments.text) for c in out.tool_calls] == [
        ("call_1", "read_mail", '{"q": "⟨ACCT_1⟩"}')
    ]
    assert seen[0]["tools"] == [schema]


def test_tool_and_assistant_messages_serialised() -> None:
    from agent.core.llm import ToolCall

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion())

    messages = [
        ChatMessage(
            "assistant", from_model(""), tool_calls=[ToolCall("c1", "t", from_model("{}"))]
        ),
        ChatMessage("tool", from_model("result"), tool_call_id="c1"),
    ]
    _client(handler).complete(messages, [])
    sent = seen[0]["messages"]
    assert sent[0]["tool_calls"][0]["function"] == {"name": "t", "arguments": "{}"}
    assert sent[1]["tool_call_id"] == "c1"


def test_default_client_missing_key_fails_at_chat_time_only() -> None:
    client = build_default_client(Settings(), KeyStore())  # no error at build time
    with pytest.raises(MissingApiKeyError):
        client.complete(_msgs("hello"), [])


def test_default_client_uses_keystore_key_and_ollama_fallback() -> None:
    ks = KeyStore()
    ks.set("nvidia_api_key", "nvapi-test")
    auth: list[str] = []
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url.host)
        auth.append(request.headers["authorization"])
        if request.url.port == 11434:
            return httpx.Response(200, json=_completion("local"))
        return httpx.Response(503, json={"error": {}})

    client = build_default_client(
        Settings(), ks, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None,
    )  # fmt: skip
    out = client.complete(_msgs("hello"), [])
    assert out.content is not None and out.content.text == "local"
    assert auth[0] == "Bearer nvapi-test"
    assert auth[-1] == "Bearer ollama"
    assert urls[0] == "integrate.api.nvidia.com"


@pytest.mark.parametrize(
    "url", ["http://192.168.1.5:11434/v1", "http://example.com/v1", "http://localhost:11434/v1"]
)
def test_ollama_url_must_be_loopback(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        build_default_client(Settings(ollama_base_url=url), KeyStore())
