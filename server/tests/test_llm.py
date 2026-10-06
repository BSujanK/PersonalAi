from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent.config import Settings
from agent.core.llm import (
    ChatMessage,
    LLMNotConfigured,
    LLMRateLimited,
    LLMUnavailable,
    MissingApiKeyError,
    MissingModelError,
    OpenAICompatClient,
    UnredactedPayloadError,
    build_default_client,
    estimate_tokens,
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


def _routed(
    handler: Handler,
    sleeps: list[float] | None = None,
    *,
    key: bool = True,
    **overrides: Any,
) -> Any:
    ks = KeyStore()
    if key:
        ks.set("nvidia_api_key", "nvapi-test")
    record = sleeps if sleeps is not None else []
    settings = Settings(**{"model_primary": "prim-model", **overrides})
    return build_default_client(
        settings, ks, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=record.append,
    )  # fmt: skip


class _Upstream:
    """Mock server: per-model status codes, records the models requested."""

    def __init__(self, **status: int) -> None:
        self.status = status
        self.models: list[str] = []
        self.auth: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        self.models.append(model)
        self.auth.append(request.headers["authorization"])
        code = self.status.get(model, 200)
        if code == 200:
            return httpx.Response(200, json=_completion(f"from {model}"))
        return httpx.Response(code, json={"error": {}})


def test_short_input_uses_primary_and_logs_no_content(caplog: pytest.LogCaptureFixture) -> None:
    up = _Upstream()
    caplog.set_level(logging.INFO, logger="agent.core.llm")
    out = _routed(up, model_long="long-model").complete(_msgs("secret words here"), [])
    assert up.models == ["prim-model"]
    assert out.route == "primary"
    assert out.content is not None and out.content.text == "from prim-model"
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "route=primary" in logged and "model=prim-model" in logged
    assert "secret words" not in logged and "nvapi-test" not in logged


def test_long_input_uses_long_model_when_configured() -> None:
    up = _Upstream()
    out = _routed(up, model_long="long-model", long_context_tokens=10).complete(
        _msgs("x" * 400), []
    )
    assert up.models == ["long-model"]
    assert out.route == "long"


def test_long_input_without_long_model_stays_primary() -> None:
    up = _Upstream()
    out = _routed(up, long_context_tokens=10).complete(_msgs("x" * 400), [])
    assert up.models == ["prim-model"]
    assert out.route == "primary"


def test_threshold_boundary_estimate_equal_stays_primary() -> None:
    messages = _msgs("x" * 40)
    estimate = estimate_tokens(messages, [])
    up = _Upstream()
    _routed(up, model_long="long-model", long_context_tokens=estimate).complete(messages, [])
    assert up.models == ["prim-model"]
    up = _Upstream()
    _routed(up, model_long="long-model", long_context_tokens=estimate - 1).complete(messages, [])
    assert up.models == ["long-model"]


def test_estimate_tokens_counts_messages_tool_calls_and_tools() -> None:
    from agent.core.llm import ToolCall

    messages = [
        ChatMessage("user", from_model("abcd")),
        ChatMessage(
            "assistant", from_model(""), tool_calls=[ToolCall("1", "ab", from_model("cdef"))]
        ),
    ]
    tools = [{"a": 1}]
    chars = 4 + 0 + 2 + 4 + len(json.dumps(tools))
    assert estimate_tokens(messages, tools) == -(-chars // 4)


def test_primary_429_fails_over_to_fallback_without_sleeping() -> None:
    up = _Upstream(**{"prim-model": 429})
    sleeps: list[float] = []
    out = _routed(up, sleeps, model_fallback="fb-model").complete(_msgs("hello"), [])
    assert up.models == ["prim-model", "fb-model"]
    assert sleeps == []
    assert out.route == "fallback"


def test_primary_503_fails_over_at_once_when_a_fallback_exists() -> None:
    # A congested free-tier model must not stall the chat through retries and backoff.
    up = _Upstream(**{"prim-model": 503})
    sleeps: list[float] = []
    out = _routed(up, sleeps, model_fallback="fb-model").complete(_msgs("hello"), [])
    assert up.models == ["prim-model", "fb-model"]
    assert sleeps == []
    assert out.route == "fallback"


def test_slow_primary_times_out_once_then_fallback() -> None:
    calls: list[str] = []
    fallback = _Upstream()

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "prim-model":
            raise httpx.ReadTimeout("slow", request=request)
        return fallback(request)

    sleeps: list[float] = []
    out = _routed(handler, sleeps, model_fallback="fb-model").complete(_msgs("hello"), [])
    assert calls == ["prim-model", "fb-model"]
    assert sleeps == []
    assert out.route == "fallback"


def test_last_cloud_route_still_retries_with_backoff() -> None:
    up = _Upstream(**{"prim-model": 503})
    sleeps: list[float] = []
    _routed(up, sleeps).complete(_msgs("hello"), [])  # no fallback: primary is the last route
    assert up.models[:4] == ["prim-model"] * 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_primary_and_fallback_down_uses_local_ollama() -> None:
    ports: list[int | None] = []
    up = _Upstream(**{"prim-model": 503, "fb-model": 503})

    def handler(request: httpx.Request) -> httpx.Response:
        ports.append(request.url.port)
        return up(request)

    out = _routed(handler, model_fallback="fb-model").complete(_msgs("hello"), [])
    assert out.route == "local"
    assert ports[-1] == 11434
    assert up.auth[-1] == "Bearer ollama"
    assert up.auth[0] == "Bearer nvapi-test"


def test_no_fallback_primary_429_is_retried_then_local() -> None:
    up = _Upstream(**{"prim-model": 429})
    sleeps: list[float] = []
    out = _routed(up, sleeps).complete(_msgs("hello"), [])
    assert up.models[:4] == ["prim-model"] * 4
    assert sleeps == [1.0, 2.0, 4.0]
    assert out.route == "local"


def test_everything_down_raises_unavailable() -> None:
    up = _Upstream(**{"prim-model": 503, "fb-model": 503, "qwen2.5:3b": 503})
    with pytest.raises(LLMUnavailable, match="all routes failed"):
        _routed(up, model_fallback="fb-model").complete(_msgs("hello"), [])


def test_fallback_equal_to_primary_is_skipped() -> None:
    up = _Upstream(**{"prim-model": 429})
    sleeps: list[float] = []
    out = _routed(up, sleeps, model_fallback="prim-model").complete(_msgs("hello"), [])
    assert up.models.count("prim-model") == 4  # retried with backoff, no duplicate hop
    assert sleeps == [1.0, 2.0, 4.0]
    assert out.route == "local"


def test_missing_primary_model_fails_at_chat_time_only() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_completion())

    client = _routed(handler, model_primary="")  # no error at build time
    with pytest.raises(MissingModelError, match="PERSONALAI_MODEL_PRIMARY"):
        client.complete(_msgs("hello"), [])
    assert calls == []
    assert issubclass(MissingModelError, LLMNotConfigured)


def test_default_client_missing_key_fails_at_chat_time_only() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_completion())

    client = _routed(handler, key=False)  # no error at build time
    with pytest.raises(MissingApiKeyError):
        client.complete(_msgs("hello"), [])
    assert calls == []


def test_router_refuses_plain_str_before_any_route() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_completion())

    bad = ChatMessage("user", "raw 4111111111111111")  # type: ignore[arg-type]
    with pytest.raises(UnredactedPayloadError):
        _routed(handler, model_fallback="fb-model").complete([bad], [])
    assert calls == []


def test_rate_limit_without_retry_raises_immediately() -> None:
    sleeps: list[float] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {}})

    with pytest.raises(LLMRateLimited):
        _client(handler, sleeps, retry_rate_limit=False).complete(_msgs("hello"), [])
    assert sleeps == []


def test_persistent_rate_limit_raises_rate_limited_after_retries() -> None:
    sleeps: list[float] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {}})

    with pytest.raises(LLMRateLimited):
        _client(handler, sleeps, max_retries=2).complete(_msgs("hello"), [])
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    "url", ["http://192.168.1.5:11434/v1", "http://example.com/v1", "http://localhost:11434/v1"]
)
def test_ollama_url_must_be_loopback(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        build_default_client(Settings(ollama_base_url=url), KeyStore())


def test_local_route_skipped_when_estimate_exceeds_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages = _msgs("x" * 400)
    estimate = estimate_tokens(messages, [])
    up = _Upstream(**{"prim-model": 503})
    caplog.set_level(logging.INFO, logger="agent.core.llm")
    with pytest.raises(LLMUnavailable, match="all routes failed"):
        _routed(up, local_context_tokens=estimate - 1).complete(messages, [])
    assert set(up.models) == {"prim-model"}  # the Ollama model never receives a request
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert f"llm local route skipped est_tokens={estimate} limit={estimate - 1}" in logged


def test_local_route_serves_when_estimate_at_limit() -> None:
    messages = _msgs("x" * 400)
    estimate = estimate_tokens(messages, [])
    up = _Upstream(**{"prim-model": 503})
    out = _routed(up, local_context_tokens=estimate).complete(messages, [])
    assert out.route == "local"


def _sse_body(*events: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def _delta(delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def _sse_response(*events: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200, content=_sse_body(*events), headers={"content-type": "text/event-stream"}
    )


def _stream(client: Any, text: str = "hi") -> tuple[Any, list[str], list[int]]:
    deltas: list[str] = []
    resets: list[int] = []
    response = client.stream_complete(
        _msgs(text), [], lambda d: deltas.append(d.text), lambda: resets.append(1)
    )
    return response, deltas, resets


def test_stream_accumulates_content_and_tool_calls() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _sse_response(
            _delta({"role": "assistant", "content": ""}),
            _delta({"content": "Hel"}),
            _delta({"content": "lo"}),
            _delta(
                {
                    "tool_calls": [
                        {"index": 0, "id": "t1", "type": "function",
                         "function": {"name": "read_mail", "arguments": '{"a"'}},
                        {"index": 1, "id": "t2", "type": "function",
                         "function": {"name": "other", "arguments": ""}},
                    ]
                }
            ),
            _delta({"tool_calls": [{"index": 0, "function": {"arguments": ": 1}"}}]}),
            {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "m",
             "choices": []},
        )  # fmt: skip

    response, deltas, resets = _stream(_client(handler))
    assert seen[0]["stream"] is True
    assert deltas == ["Hel", "lo"]
    assert resets == []
    assert response.content is not None and response.content.text == "Hello"
    assert [(c.id, c.name, c.arguments.text) for c in response.tool_calls] == [
        ("t1", "read_mail", '{"a": 1}'),
        ("t2", "other", ""),
    ]


def test_stream_without_content_returns_none() -> None:
    client = _client(lambda _r: _sse_response(_delta({"role": "assistant"})))
    response, deltas, _ = _stream(client)
    assert response.content is None and response.tool_calls == [] and deltas == []


def test_stream_refuses_plain_str_before_network() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        raise AssertionError("network touched")

    bad = [ChatMessage("user", "raw")]  # type: ignore[arg-type]
    with pytest.raises(UnredactedPayloadError):
        _client(handler).stream_complete(bad, [], lambda _d: None, lambda: None)


def test_stream_retries_before_anything_is_emitted() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": {}})
        return _sse_response(_delta({"content": "ok"}))

    sleeps: list[float] = []
    response, deltas, _ = _stream(_client(handler, sleeps))
    assert len(calls) == 3 and sleeps == [1.0, 2.0]
    assert deltas == ["ok"] and response.content.text == "ok"


def test_stream_429_without_retry_raises_rate_limited() -> None:
    client = _client(lambda _r: httpx.Response(429, json={"error": {}}), retry_rate_limit=False)
    with pytest.raises(LLMRateLimited):
        _stream(client)


def test_stream_4xx_is_not_retried() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {}})

    with pytest.raises(LLMUnavailable, match="rejected"):
        _stream(_client(handler))
    assert len(calls) == 1


class _BrokenBody(httpx.SyncByteStream):
    def __init__(self, first: bytes) -> None:
        self._first = first

    def __iter__(self) -> Any:
        yield self._first
        raise httpx.ReadError("boom")


def test_stream_failure_after_emit_is_not_retried() -> None:
    calls: list[int] = []
    first = f"data: {json.dumps(_delta({'content': 'par'}))}\n\n".encode()

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            200, stream=_BrokenBody(first), headers={"content-type": "text/event-stream"}
        )

    deltas: list[str] = []
    with pytest.raises(LLMUnavailable, match="stream interrupted"):
        _client(handler).stream_complete(
            _msgs("hi"), [], lambda d: deltas.append(d.text), lambda: None
        )
    assert deltas == ["par"] and len(calls) == 1


def test_stream_failure_before_emit_is_retried() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                200, stream=_BrokenBody(b": keepalive\n\n"),
                headers={"content-type": "text/event-stream"},
            )  # fmt: skip
        return _sse_response(_delta({"content": "ok"}))

    _, deltas, _ = _stream(_client(handler))
    assert len(calls) == 2 and deltas == ["ok"]


def test_router_stream_serves_from_primary() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return _sse_response(_delta({"content": "a"}), _delta({"content": "b"}))

    response, deltas, _ = _stream(_routed(handler))
    assert deltas == ["a", "b"] and response.route == "primary"


def test_router_stream_resets_and_falls_back_after_partial_output() -> None:
    first = f"data: {json.dumps(_delta({'content': 'par'}))}\n\n".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == "prim-model":
            return httpx.Response(
                200, stream=_BrokenBody(first), headers={"content-type": "text/event-stream"}
            )
        return _sse_response(_delta({"content": "full"}))

    events: list[str] = []
    response = _routed(handler, model_fallback="fb-model").stream_complete(
        _msgs("hi"), [], lambda d: events.append(d.text), lambda: events.append("<reset>")
    )
    assert events == ["par", "<reset>", "full"]
    assert response.route == "fallback"


def test_router_stream_skips_local_over_limit_and_raises() -> None:
    messages = _msgs("x" * 400)
    up = _Upstream(**{"prim-model": 503})
    with pytest.raises(LLMUnavailable, match="all routes failed"):
        _routed(up, local_context_tokens=1).stream_complete(
            messages, [], lambda _d: None, lambda: None
        )
    assert set(up.models) == {"prim-model"}


def test_failed_primary_is_tried_last_until_its_cooldown_ends() -> None:
    from agent.core.llm import ROUTE_COOLDOWN_SECONDS, ModelRouter

    now = [1000.0]
    up = _Upstream(**{"prim-model": 503})
    router = _routed(up, model_fallback="fb-model")
    assert isinstance(router, ModelRouter)
    router._clock = lambda: now[0]
    router.complete(_msgs("one"), [])
    assert up.models == ["prim-model", "fb-model"]
    up.models.clear()
    router.complete(_msgs("two"), [])  # primary is cooling down: fallback goes first
    assert up.models == ["fb-model"]
    up.models.clear()
    now[0] += ROUTE_COOLDOWN_SECONDS + 1
    router.complete(_msgs("three"), [])  # cooldown over: primary is tried first again
    assert up.models[0] == "prim-model"


def test_fallback_list_is_tried_in_order_and_deduplicated() -> None:
    up = _Upstream(**{"prim-model": 503, "fb-a": 503})
    out = _routed(up, model_fallback="fb-a, fb-b, prim-model, fb-a").complete(_msgs("hi"), [])
    assert up.models[:2] == ["prim-model", "fb-a"]
    assert "fb-b" in up.models and up.models.count("prim-model") == 1
    assert out.route == "fallback2"


def test_settings_parse_fallback_list() -> None:
    from agent.config import Settings

    settings = Settings.from_env({"PERSONALAI_MODEL_FALLBACK": "a, b,,a ,c"})
    assert settings.model_fallbacks == ("a", "b", "c")
