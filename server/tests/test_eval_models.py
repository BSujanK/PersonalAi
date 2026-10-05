"""The model evaluation script: scenarios are satisfiable, checks discriminate, numbers are exact.

Everything runs over the in-memory world with scripted models or ``httpx.MockTransport``; no test
touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import keyring
import pytest

from agent.core.llm import ChatMessage, LLMClient, LLMResponse
from agent.core.redact import from_model
from agent.store.keystore import KeyStore
from tests.security_support import ATTACKER, accounts_from, calls, discovery, says

BASE_URL = "https://integrate.api.nvidia.com/v1"
SECRET_KEY = "nvapi-test-key-not-real"


def _load() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "eval_models.py"
    spec = importlib.util.spec_from_file_location("eval_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_models"] = module  # dataclasses resolve string annotations through it
    spec.loader.exec_module(module)
    return module


em = _load()
SCENARIOS = em.SCENARIOS
BY_ID = {s.id: s for s in SCENARIOS}
Step = Callable[[Sequence[ChatMessage]], LLMResponse]


class ScriptedModel:
    """Stateless scripted model: assistant turn N plays step N (the last step repeats)."""

    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = steps

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        turn = sum(1 for m in messages if m.role == "assistant")
        return self._steps[min(turn, len(self._steps) - 1)](messages)


class ByPrompt:
    """Plays the reference of whichever scenario the conversation's first user message is."""

    def __init__(self, scenarios: Sequence[Any]) -> None:
        self._by_prompt = {s.prompt: s.reference for s in scenarios}

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        prompt = next(m for m in messages if m.role == "user").content.text
        return ScriptedModel(self._by_prompt[prompt]).complete(messages, tools)


def _never_throttled(client: LLMClient) -> Callable[[str], tuple[LLMClient, Callable[[], int]]]:
    return lambda _model: (client, lambda: 0)


def _run(client: LLMClient, scenarios: Sequence[Any], **kwargs: Any) -> Any:
    (report,) = em.run_eval(["fake/model"], _never_throttled(client), scenarios=scenarios, **kwargs)
    return report


def _completion(content: str) -> dict[str, Any]:
    message = {"role": "assistant", "content": content}
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def test_catalogue_shape() -> None:
    ids = [s.id for s in SCENARIOS]
    assert 35 <= len(SCENARIOS) <= 45
    assert len(set(ids)) == len(ids)
    assert {s.category for s in SCENARIOS} == set(em.CATEGORIES)
    assert all(s.reference and s.prompt for s in SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_every_scenario_is_satisfiable(scenario: Any) -> None:
    report = _run(ScriptedModel(scenario.reference), [scenario])
    assert report.results == {scenario.id: True}
    assert report.errors == 0


class OnlyOk:
    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        return LLMResponse(from_model("OK"), [])


def test_a_model_that_only_says_ok_fails_everything_that_needs_work() -> None:
    report = _run(OnlyOk(), SCENARIOS)
    for s in SCENARIOS:
        if s.category in ("tool", "multi", "placeholder"):
            assert report.results[s.id] is False, s.id
    plain = {s.id: report.results[s.id] for s in SCENARIOS if s.category == "plain"}
    assert plain == {
        "plain_greeting": True,
        "plain_arithmetic": False,
        "plain_rewrite": True,
        "plain_capital": False,
        "plain_explain": True,
    }


class Obedient:
    """Reads the injected content, then does what it says: an event inviting the attacker."""

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]
    ) -> LLMResponse:
        results = sum(1 for m in messages if m.role == "tool")
        if results == 0:
            return discovery()(messages)
        if results == 2:
            account = accounts_from(messages).me
            attack = {
                "account": account,
                "summary": "Party",
                "start": "2026-10-07T10:00:00+00:00",
                "end": "2026-10-07T11:00:00+00:00",
                "description": f"Invite {ATTACKER}",
            }
            return calls(("calendar_create_event", attack), prefix="evil")(messages)
        return says("Done.")(messages)


def test_a_model_that_obeys_the_injection_fails_every_injection_scenario() -> None:
    injections = [s for s in SCENARIOS if s.category == "injection"]
    assert len(injections) >= 6
    report = _run(Obedient(), injections)
    assert not any(report.results.values())
    assert report.failed_ids == [s.id for s in injections]


def test_unreachable_model_is_an_error_not_a_crash() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "no"}})

    def client_for(model: str) -> tuple[LLMClient, Callable[[], int]]:
        return em.build_client(BASE_URL, SECRET_KEY, model, transport=httpx.MockTransport(refuse))

    (report,) = em.run_eval(["m"], client_for, scenarios=[BY_ID["plain_greeting"]])
    assert (report.passed, report.errors) == (0, 1)


def test_rate_limits_are_counted_and_retried() -> None:
    answers = [httpx.Response(429, json={"error": {"message": "slow down"}})]
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return answers.pop(0) if answers else httpx.Response(200, json=_completion("Hello!"))

    def client_for(model: str) -> tuple[LLMClient, Callable[[], int]]:
        return em.build_client(
            BASE_URL, SECRET_KEY, model, transport=httpx.MockTransport(handler), sleep=sleeps.append
        )

    reports = em.run_eval(["meta/test-model"], client_for, scenarios=[BY_ID["plain_greeting"]])
    (report,) = reports
    assert report.rate_limited == 1
    assert sleeps == [1.0]
    assert report.passed == 1
    table = em.format_table(reports)
    assert "meta/test-model" in table
    assert "100.0" in table
    assert "1/1" in table
    assert BY_ID["plain_greeting"].prompt not in table


def test_latency_percentiles_are_exact() -> None:
    chosen = [BY_ID["plain_greeting"], BY_ID["plain_arithmetic"], BY_ID["tool_balances"]]
    stamps = iter([0.0, 0.010, 1.0, 1.020, 2.0, 2.030, 3.0, 3.100])  # 4 calls: start, end each
    report = _run(ByPrompt(chosen), chosen, clock=lambda: next(stamps))
    assert report.latencies_ms == pytest.approx([10, 20, 30, 100])
    assert report.p50() == pytest.approx(20)
    assert report.p95() == pytest.approx(100)


def test_percentile_edges() -> None:
    assert em.percentile([], 50) is None
    assert em.percentile([7.0], 95) == 7.0
    assert em.percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.0


def test_table_lists_failed_ids_and_categories() -> None:
    chosen = [BY_ID["plain_arithmetic"], BY_ID["plain_greeting"], BY_ID["tool_balances"]]
    reports = em.run_eval(["m/one"], _never_throttled(OnlyOk()), scenarios=chosen)
    table = em.format_table(reports)
    assert "1/3" in table
    assert "plain_arithmetic, tool_balances" in table
    assert "1/2" in table  # plain: greeting passes, arithmetic fails
    assert json.loads(json.dumps(em.to_json(reports)))["models"][0]["failed"] == [
        "plain_arithmetic",
        "tool_balances",
    ]


def test_pacer_spaces_calls() -> None:
    now = [100.0]
    sleeps: list[float] = []
    pace = em.make_pacer(30, clock=lambda: now[0], sleep=sleeps.append)
    pace()
    now[0] += 0.5
    pace()
    assert sleeps == [pytest.approx(1.5)]
    em.make_pacer(None, clock=lambda: now[0], sleep=sleeps.append)()
    assert len(sleeps) == 1


@pytest.fixture
def secure_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(em, "assert_secure_backend", lambda: None)


def _models_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        data = [
            {"id": model, "object": "model", "created": 0, "owned_by": "x"}
            for model in ("zeta/model", "alpha/model")
        ]
        return httpx.Response(200, json={"object": "list", "data": data})

    return httpx.MockTransport(handler)


def test_list_models_prints_sorted_ids(
    secure_backend: None, capsys: pytest.CaptureFixture[str]
) -> None:
    KeyStore().set("nvidia_api_key", SECRET_KEY)
    assert em.main(["--list-models"], transport=_models_transport()) == 0
    out = capsys.readouterr()
    assert out.out.split() == ["alpha/model", "zeta/model"]
    assert SECRET_KEY not in out.out + out.err


def test_main_without_a_key_fails_quietly(
    secure_backend: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert em.main(["some/model"]) == 1
    out = capsys.readouterr()
    assert "nvidia_api_key is not in the keyring" in out.err
    assert SECRET_KEY not in out.out + out.err


def test_main_refuses_an_insecure_keyring(capsys: pytest.CaptureFixture[str]) -> None:
    KeyStore().set("nvidia_api_key", SECRET_KEY)
    assert em.main(["some/model"]) == 2  # the in-memory test backend is not an OS keyring
    out = capsys.readouterr()
    assert "insecure keyring backend" in out.err
    assert SECRET_KEY not in out.out + out.err


def test_main_needs_a_model_or_list_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert em.main([]) == 2
    assert em.main(["m", "--only", "bogus"]) == 2
    assert SECRET_KEY not in capsys.readouterr().err


def test_main_runs_and_writes_json(
    secure_backend: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    KeyStore().set("nvidia_api_key", SECRET_KEY)
    before = keyring.get_keyring()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {SECRET_KEY}"
        return httpx.Response(200, json=_completion("Hello!"))

    target = tmp_path / "out.json"
    argv = ["m/one", "m/two", "--only", "plain", "--limit", "1", "--json", str(target)]
    assert em.main(argv, transport=httpx.MockTransport(handler)) == 0
    out = capsys.readouterr().out
    assert "m/one" in out and "m/two" in out
    assert SECRET_KEY not in out
    assert "Hello!" not in out
    assert keyring.get_keyring() is before  # the fake world's keyring was only a loan
    models = json.loads(target.read_text(encoding="utf-8"))["models"]
    assert [m["model"] for m in models] == ["m/one", "m/two"]
    assert all(m["passed"] == 1 and m["total"] == 1 for m in models)
    assert SECRET_KEY not in target.read_text(encoding="utf-8")
