"""NVIDIA Build smoke test (M7, run on the laptop): key, reachability and tool calling.

Usage: uv run python scripts/check_nvidia.py

Sends one fixed, synthetic prompt (no personal data) with one dummy tool and checks the model
answers with a call to that tool. Prints only the model id and pass or fail, never the key.
"""

from __future__ import annotations

import json
import sys

from agent.config import Settings
from agent.core.llm import ChatMessage, LLMUnavailable, OpenAICompatClient
from agent.core.redact import from_model
from agent.store.keystore import InsecureKeyringError, KeyStore, assert_secure_backend

_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}
# A constant, synthetic prompt: nothing from any connector is sent.
_PROMPT = "What is the weather in Example City? Use the tool."


def main() -> int:
    try:
        assert_secure_backend()
    except InsecureKeyringError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    key = KeyStore().get("nvidia_api_key")
    if not key:
        print("FAIL: nvidia_api_key is not in the keyring (service PersonalAi)", file=sys.stderr)
        return 1
    client = OpenAICompatClient(settings.nvidia_base_url, key, settings.nvidia_model)
    try:
        response = client.complete([ChatMessage("user", from_model(_PROMPT))], [_TOOL])
    except LLMUnavailable as exc:
        print(f"FAIL: {type(exc).__name__}: the API rejected the request or is unreachable")
        return 1
    calls = [c for c in response.tool_calls if c.name == "get_weather"]
    if not calls:
        print(f"FAIL: {settings.nvidia_model} answered without calling the tool")
        return 1
    try:
        json.loads(calls[0].arguments.text)
    except ValueError:
        print(f"FAIL: {settings.nvidia_model} returned malformed tool arguments")
        return 1
    print(f"OK: {settings.nvidia_model} reachable and tool calling works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
