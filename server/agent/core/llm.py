"""LLM client. Only ``Redacted`` text may be sent (CLAUDE.md rule 3). Never logs content."""

from __future__ import annotations

import ipaddress
import json
import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import httpx
import openai

from agent.config import Settings
from agent.core.redact import Redacted, from_model
from agent.store.keystore import KeyStore

log = logging.getLogger(__name__)

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


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        http_client: httpx.Client | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 60,
        retry_rate_limit: bool = True,
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

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        wire = _to_wire(messages)  # guard runs before anything touches the network
        kwargs: dict[str, Any] = {"model": self._model, "messages": wire}
        if tools:
            kwargs["tools"] = list(tools)
        completion = self._create_with_retry(kwargs)
        choice = completion.choices[0].message
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=from_model(tc.function.arguments))
            for tc in (choice.tool_calls or [])
            if tc.type == "function"
        ]
        content = from_model(choice.content) if choice.content else None
        return LLMResponse(content=content, tool_calls=calls)

    def _create_with_retry(self, kwargs: dict[str, Any]) -> Any:
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError as exc:
                if not self._retry_rate_limit:
                    raise LLMRateLimited("rate limited (429)") from None
                reason = type(exc).__name__
                rate_limited = True
            except openai.APIConnectionError as exc:
                reason = type(exc).__name__
                rate_limited = False
            except openai.APIStatusError as exc:
                if exc.status_code < 500:
                    raise LLMUnavailable(f"request rejected ({exc.status_code})") from None
                reason = f"http_{exc.status_code}"
                rate_limited = False
            if attempt == self._max_retries:
                if rate_limited:
                    raise LLMRateLimited(f"retries exhausted ({reason})")
                raise LLMUnavailable(f"retries exhausted ({reason})")
            log.warning("llm retry %d after %s", attempt + 1, reason)
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover


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
    ) -> None:
        self._settings = settings
        self._keystore = keystore
        self._http_client = http_client
        self._sleep = sleep

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
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
        if settings.model_fallback and settings.model_fallback != cloud[0][1]:
            cloud.append(("fallback", settings.model_fallback))

        chain: list[tuple[str, OpenAICompatClient, str]] = []
        for index, (name, model) in enumerate(cloud):
            client = OpenAICompatClient(
                settings.nvidia_base_url,
                key,
                model,
                http_client=self._http_client,
                sleep=self._sleep,
                retry_rate_limit=index == len(cloud) - 1,
            )
            chain.append((name, client, model))
        local = OpenAICompatClient(
            settings.ollama_base_url,
            "ollama",
            settings.ollama_model,
            http_client=self._http_client,
            sleep=self._sleep,
        )
        chain.append(("local", local, settings.ollama_model))

        for hops, (name, client, model) in enumerate(chain):
            try:
                response = client.complete(messages, tools)
            except LLMUnavailable as exc:
                if hops + 1 < len(chain):
                    log.warning(
                        "llm route=%s model=%s failed (%s), trying %s",
                        name,
                        model,
                        type(exc).__name__,
                        chain[hops + 1][0],
                    )
                continue
            log.info(
                "llm served route=%s model=%s est_tokens=%d hops=%d",
                name,
                model,
                estimate,
                hops,
            )
            return replace(response, route=name)
        raise LLMUnavailable("all routes failed")


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
