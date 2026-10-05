"""LLM client. Only ``Redacted`` text may be sent (CLAUDE.md rule 3). Never logs content."""

from __future__ import annotations

import ipaddress
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


class MissingApiKeyError(RuntimeError):
    """No NVIDIA API key is stored in the keyring."""


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
            except (openai.RateLimitError, openai.APIConnectionError) as exc:
                reason = type(exc).__name__
            except openai.APIStatusError as exc:
                if exc.status_code < 500:
                    raise LLMUnavailable(f"request rejected ({exc.status_code})") from None
                reason = f"http_{exc.status_code}"
            if attempt == self._max_retries:
                raise LLMUnavailable(f"retries exhausted ({reason})")
            log.warning("llm retry %d after %s", attempt + 1, reason)
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover


class FallbackClient:
    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self._primary = primary
        self._fallback = fallback

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        try:
            return self._primary.complete(messages, tools)
        except LLMUnavailable:
            log.warning("primary llm unavailable, using fallback")
            return self._fallback.complete(messages, tools)


class _KeyedClient:
    """Fetches the API key at call time so a missing key fails at chat time, not at startup."""

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
        key = self._keystore.get("nvidia_api_key")
        if not key:
            raise MissingApiKeyError("nvidia_api_key is not set in the keyring")
        client = OpenAICompatClient(
            self._settings.nvidia_base_url,
            key,
            self._settings.nvidia_model,
            http_client=self._http_client,
            sleep=self._sleep,
        )
        return client.complete(messages, tools)


def _require_loopback(url: str) -> None:
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
    _require_loopback(settings.ollama_base_url)
    primary = _KeyedClient(settings, keystore, http_client, sleep)
    fallback = OpenAICompatClient(
        settings.ollama_base_url,
        "ollama",
        settings.ollama_model,
        http_client=http_client,
        sleep=sleep,
    )
    return FallbackClient(primary, fallback)
