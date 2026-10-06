"""LLM client. Only ``Redacted`` text may be sent (CLAUDE.md rule 3). Never logs content."""

from __future__ import annotations

import ipaddress
import json
import logging
import math
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable
from urllib.parse import urlparse

import httpx
import openai

from agent.config import Settings
from agent.core.redact import Redacted, from_model
from agent.store.keystore import KeyStore

log = logging.getLogger(__name__)

T = TypeVar("T")
DeltaSink = Callable[[Redacted], None]

Role = Literal["system", "user", "assistant", "tool"]


class LLMUnavailable(RuntimeError):
    """The model could not be reached after retries (or rejected the request)."""


class LLMRateLimited(LLMUnavailable):
    """The model answered 429 (and, if retries were allowed, kept doing so)."""


class LLMNotConfigured(RuntimeError):
    """The cloud model cannot be used until the owner finishes configuring it."""


class MissingApiKeyError(LLMNotConfigured):
    """No NVIDIA API key is stored in the keyring."""


class MissingModelError(LLMNotConfigured):
    """No primary model id is configured."""


class UnredactedPayloadError(TypeError):
    """Something other than ``Redacted`` was about to be sent to the model."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Redacted  # raw JSON string from the model, already in placeholder space


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: Redacted
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: Redacted | None
    tool_calls: list[ToolCall]
    route: str | None = None  # name of the route that served this response


class LLMClient(Protocol):
    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse: ...


@runtime_checkable
class StreamingLLMClient(Protocol):
    def stream_complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: DeltaSink,
        on_reset: Callable[[], None],
    ) -> LLMResponse: ...


@runtime_checkable
class RouteExcludingLLMClient(Protocol):
    """A client that can answer on a route other than the ones named (see ``LLMResponse.route``)."""

    def complete_excluding(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        exclude: Collection[str],
    ) -> LLMResponse: ...

    def stream_complete_excluding(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: DeltaSink,
        on_reset: Callable[[], None],
        exclude: Collection[str],
    ) -> LLMResponse: ...


def _to_wire(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg.content, Redacted):
            raise UnredactedPayloadError("message content must be Redacted")
        item: dict[str, Any] = {"role": msg.role, "content": msg.content.text}
        if msg.tool_call_id is not None:
            item["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            calls = []
            for call in msg.tool_calls:
                if not isinstance(call.arguments, Redacted):
                    raise UnredactedPayloadError("tool call arguments must be Redacted")
                calls.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments.text},
                    }
                )
            item["tool_calls"] = calls
        wire.append(item)
    return wire


def estimate_tokens(messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]) -> int:
    """Rough prompt size (ceil of chars / 4); only ever reads ``Redacted`` text."""
    chars = 0
    for item in _to_wire(messages):
        chars += len(item["content"])
        for call in item.get("tool_calls", ()):
            chars += len(call["function"]["name"]) + len(call["function"]["arguments"])
    chars += len(json.dumps(list(tools)))
    return math.ceil(chars / 4)


DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_RETRIES = 3


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        http_client: httpx.Client | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retry_rate_limit: bool = True,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
            max_retries=0,
            timeout=timeout,
        )
        self._model = model
        self._max_retries = max_retries
        self._sleep = sleep
        self._retry_rate_limit = retry_rate_limit
        self._extra_body = extra_body

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        kwargs = self._kwargs(messages, tools)  # guard runs before anything touches the network
        completion = self._with_retry(lambda: self._client.chat.completions.create(**kwargs))
        choice = completion.choices[0].message
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=from_model(tc.function.arguments))
            for tc in (choice.tool_calls or [])
            if tc.type == "function"
        ]
        content = from_model(choice.content) if choice.content else None
        return LLMResponse(content=content, tool_calls=calls)

    def stream_complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: DeltaSink,
        on_reset: Callable[[], None],  # unused: this client never retries after emitting
    ) -> LLMResponse:
        kwargs = self._kwargs(messages, tools)
        kwargs["stream"] = True
        emitted = False

        def sink(delta: Redacted) -> None:
            nonlocal emitted
            emitted = True
            on_delta(delta)

        return self._with_retry(
            lambda: self._stream_once(kwargs, sink), retryable=lambda: not emitted
        )

    def _kwargs(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self._model, "messages": _to_wire(messages)}
        if tools:
            kwargs["tools"] = list(tools)
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        return kwargs

    def _stream_once(self, kwargs: dict[str, Any], on_delta: DeltaSink) -> LLMResponse:
        parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        for chunk in self._client.chat.completions.create(**kwargs):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                parts.append(delta.content)
                on_delta(from_model(delta.content))
            for tc in delta.tool_calls or []:
                entry = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    entry["id"] = tc.id
                if tc.function is not None:
                    if tc.function.name and not entry["name"]:
                        entry["name"] = tc.function.name
                    entry["arguments"] += tc.function.arguments or ""
        tool_calls = [
            ToolCall(id=e["id"], name=e["name"], arguments=from_model(e["arguments"]))
            for _, e in sorted(calls.items())
        ]
        text = "".join(parts)
        return LLMResponse(content=from_model(text) if text else None, tool_calls=tool_calls)

    def _with_retry(
        self, attempt_call: Callable[[], T], retryable: Callable[[], bool] = lambda: True
    ) -> T:
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            try:
                return attempt_call()
            except (openai.APIError, httpx.HTTPError) as exc:
                if not retryable():
                    raise LLMUnavailable("stream interrupted") from None
                if isinstance(exc, openai.RateLimitError):
                    if not self._retry_rate_limit:
                        raise LLMRateLimited("rate limited (429)") from None
                    reason = type(exc).__name__
                    rate_limited = True
                elif isinstance(exc, openai.APIStatusError):
                    if exc.status_code < 500:
                        raise LLMUnavailable(f"request rejected ({exc.status_code})") from None
                    reason = f"http_{exc.status_code}"
                    rate_limited = False
                else:
                    reason = type(exc).__name__
                    rate_limited = False
            if attempt == self._max_retries:
                if rate_limited:
                    raise LLMRateLimited(f"retries exhausted ({reason})")
                raise LLMUnavailable(f"retries exhausted ({reason})")
            log.warning("llm retry %d after %s", attempt + 1, reason)
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover


# Sent to NVIDIA routes unless PERSONALAI_CLOUD_THINKING is on: reasoning models otherwise
# stream their thinking into the reply text and answer far more slowly.
NO_THINKING: dict[str, Any] = {"chat_template_kwargs": {"enable_thinking": False}}


def cloud_extra_body(settings: Settings) -> dict[str, Any] | None:
    return None if settings.cloud_thinking else NO_THINKING


ROUTE_COOLDOWN_SECONDS = 300


class ModelRouter:
    """Routes each call across primary/long, fallback and local models.

    The model ids and the API key are read at call time, so a missing model or key fails at chat
    time rather than at startup, and neither falls back to Ollama.
    """

    def __init__(
        self,
        settings: Settings,
        keystore: KeyStore,
        http_client: httpx.Client | None,
        sleep: Callable[[float], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._keystore = keystore
        self._http_client = http_client
        self._sleep = sleep
        self._clock = clock
        # Cloud models that just failed: tried last until this monotonic time (circuit breaker),
        # so a congested model does not cost every call of a multi-step turn its timeout.
        self._down_until: dict[str, float] = {}

    def _build_chain(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> tuple[list[tuple[str, OpenAICompatClient, str]], int]:
        settings = self._settings
        estimate = estimate_tokens(messages, tools)  # guard runs before any route
        if not settings.model_primary:
            raise MissingModelError("PERSONALAI_MODEL_PRIMARY is not set")
        key = self._keystore.get("nvidia_api_key")
        if not key:
            raise MissingApiKeyError("nvidia_api_key is not set in the keyring")

        first = "primary"
        if settings.model_long and estimate > settings.long_context_tokens:
            first = "long"
        cloud = [(first, settings.model_long if first == "long" else settings.model_primary)]
        for model in settings.model_fallbacks:
            if all(model != existing for _, existing in cloud):
                name = "fallback" if len(cloud) == 1 else f"fallback{len(cloud)}"
                cloud.append((name, model))
        now = self._clock()
        cloud.sort(key=lambda route: self._down_until.get(route[1], 0.0) > now)  # stable

        chain: list[tuple[str, OpenAICompatClient, str]] = []
        for index, (name, model) in enumerate(cloud):
            last = index == len(cloud) - 1
            client = OpenAICompatClient(
                settings.nvidia_base_url,
                key,
                model,
                http_client=self._http_client,
                sleep=self._sleep,
                retry_rate_limit=last,
                extra_body=cloud_extra_body(settings),
                # Only the last cloud route waits and retries; earlier ones get one short try.
                timeout=DEFAULT_TIMEOUT_SECONDS if last else settings.llm_failover_seconds,
                max_retries=DEFAULT_MAX_RETRIES if last else 0,
            )
            chain.append((name, client, model))
        if estimate <= settings.local_context_tokens:
            local = OpenAICompatClient(
                settings.ollama_base_url,
                "ollama",
                settings.ollama_model,
                http_client=self._http_client,
                sleep=self._sleep,
            )
            chain.append(("local", local, settings.ollama_model))
        else:
            log.info(
                "llm local route skipped est_tokens=%d limit=%d",
                estimate,
                settings.local_context_tokens,
            )
        return chain, estimate

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        return self.complete_excluding(messages, tools, ())

    def complete_excluding(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        exclude: Collection[str],
    ) -> LLMResponse:
        chain, estimate = self._routes(messages, tools, exclude)
        for hops, (name, client, model) in enumerate(chain):
            try:
                response = client.complete(messages, tools)
            except LLMUnavailable as exc:
                self._on_failure(chain, hops, exc)
                continue
            self._on_served(name, model, estimate, hops)
            return replace(response, route=name)
        raise LLMUnavailable("all routes failed")

    def stream_complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: DeltaSink,
        on_reset: Callable[[], None],
    ) -> LLMResponse:
        return self.stream_complete_excluding(messages, tools, on_delta, on_reset, ())

    def stream_complete_excluding(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        on_delta: DeltaSink,
        on_reset: Callable[[], None],
        exclude: Collection[str],
    ) -> LLMResponse:
        chain, estimate = self._routes(messages, tools, exclude)
        for hops, (name, client, model) in enumerate(chain):
            emitted = False

            def sink(delta: Redacted) -> None:
                nonlocal emitted
                emitted = True
                on_delta(delta)

            try:
                response = client.stream_complete(messages, tools, sink, on_reset)
            except LLMUnavailable as exc:
                if emitted:
                    on_reset()  # the client discards what this route already showed
                self._on_failure(chain, hops, exc)
                continue
            self._on_served(name, model, estimate, hops)
            return replace(response, route=name)
        raise LLMUnavailable("all routes failed")

    def _routes(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        exclude: Collection[str],
    ) -> tuple[list[tuple[str, OpenAICompatClient, str]], int]:
        """The routes to try in order, without the ones named in ``exclude``."""
        chain, estimate = self._build_chain(messages, tools)
        if exclude:
            chain = [route for route in chain if route[0] not in exclude]
            if not chain:
                raise LLMUnavailable("no other route")
        return chain, estimate

    def _on_failure(
        self, chain: list[tuple[str, OpenAICompatClient, str]], hops: int, exc: LLMUnavailable
    ) -> None:
        name, _, model = chain[hops]
        if name != "local":
            self._down_until[model] = self._clock() + ROUTE_COOLDOWN_SECONDS
        if hops + 1 < len(chain):
            log.warning(
                "llm route=%s model=%s failed (%s), trying %s",
                chain[hops][0],
                chain[hops][2],
                type(exc).__name__,
                chain[hops + 1][0],
            )

    def _on_served(self, name: str, model: str, estimate: int, hops: int) -> None:
        self._down_until.pop(model, None)
        log.info("llm served route=%s model=%s est_tokens=%d hops=%d", name, model, estimate, hops)


def require_loopback(url: str) -> None:
    """Refuse any Ollama base URL whose host is not a loopback IP literal."""
    host = urlparse(url).hostname or ""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("ollama base url host must be a loopback IP literal") from None
    if not addr.is_loopback:
        raise ValueError("ollama base url must be loopback")


def build_default_client(
    settings: Settings,
    keystore: KeyStore,
    http_client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> LLMClient:
    require_loopback(settings.ollama_base_url)
    return ModelRouter(settings, keystore, http_client, sleep)
