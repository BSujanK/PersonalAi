from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    scopes_for,
    token_secret_name,
)
from agent.golive.service import LIST_PROCESSES
from agent.golive.setup import run_setup
from agent.golive.system import NOT_FOUND, CommandResult, HttpResult
from agent.store.keystore import KeyStore

KEY = "nvapi-FAKEKEY1234567890"
TAVILY_KEY = "tvly-FAKEKEY1234567890"
MODELS = ["vendor/model-a", "vendor/model-b", "vendor/model-c"]
TAILSCALE_IP = "100.101.102.103"
FORBIDDEN_POWER = ("/change", "/setacvalueindex", "/setactive")


class FakeSystem:
    def __init__(self, server_dir: Path, platform: str = "win32") -> None:
        self.platform = platform
        self.server_dir = server_dir
        self.keystore = KeyStore()
        self.env: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.runs: list[list[str]] = []
        self.interactive: list[list[str]] = []
        self.ollama: list[str] | None = []
        self.task_status: str | None = None  # None: not installed
        self.power_ok = False
        self.tailscale = True
        self.headers: list[Mapping[str, str]] = []
        self.log = ""  # agent.log, as far as restart_server reads it

    def python_version(self) -> tuple[int, int, int]:
        return (3, 12, 4)

    def which(self, name: str) -> str | None:
        return f"C:/tools/{name}.exe"

    def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
        self.runs.append(list(argv))
        if argv[0] == "tailscale":
            return CommandResult(0, f"{TAILSCALE_IP}\n") if self.tailscale else CommandResult(1, "")
        if tuple(argv) == LIST_PROCESSES:  # a server is up exactly while the task is running
            row = {"pid": 1, "ppid": 0, "name": "python.exe", "cmd": "python -m agent serve"}
            row["started"] = "2026-10-05T12:00:00+00:00"
            return CommandResult(0, json.dumps([row] if self.task_status == "Running" else []))
        if argv[0] == "schtasks":
            if self.task_status is None:
                return CommandResult(1, "")
            if argv[1] == "/Run":
                self.task_status = "Running"
                self.log += "server started pid=1\n"
            elif argv[1] == "/End":
                self.task_status = "Ready"
            return CommandResult(0, f"TaskName: x\nStatus: {self.task_status}\n")
        if argv[0] == "powercfg":
            index = "0x00000000" if self.power_ok else "0x00000708"
            return CommandResult(0, f"Current AC Power Setting Index: {index}\n")
        return CommandResult(NOT_FOUND, "")

    def run_interactive(self, argv: Sequence[str]) -> int:
        args = list(argv)
        self.interactive.append(args)
        joined = " ".join(args)
        if args[:2] == ["uv", "sync"]:
            (self.server_dir / ".venv").mkdir(exist_ok=True)
        elif args[:2] == ["ollama", "pull"]:
            assert self.ollama is not None
            self.ollama.append(args[2])
        elif "install_task.ps1" in joined:
            self.task_status = "Ready"
        elif "setup_google_oauth.py" in joined:
            self._fake_oauth(args)
        return 0

    def _fake_oauth(self, args: list[str]) -> None:
        account = args[args.index("--account") + 1]
        services = args[args.index("--services") + 1].split(",")
        if "--client-secret" in args:
            self.keystore.set(CLIENT_SECRET_NAME, json.dumps({"installed": {}}))
        scopes = list(scopes_for(services))
        self.keystore.set(token_secret_name(account), json.dumps({"scopes": scopes}))

    def http_get(
        self, url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10
    ) -> HttpResult:
        if url.endswith("/api/tags"):
            if self.ollama is None:
                return HttpResult(0)
            return HttpResult(200, {"models": [{"name": m} for m in self.ollama]})
        self.headers.append(dict(headers or {}))
        return HttpResult(200, {"data": [{"id": m} for m in MODELS]})

    def port_is_free(self, host: str, port: int) -> bool:
        return True

    def file_size(self, path: Path) -> int:
        return len(self.log.encode())

    def read_text_from(self, path: Path, offset: int) -> str:
        return self.log.encode()[offset:].decode()

    def user_env(self, name: str) -> str | None:
        return self.env.get(name)

    def set_user_env(self, name: str, value: str) -> None:
        self.set_calls.append((name, value))
        self.env[name] = value


Answer = str | bool | BaseException | Callable[[], str]


class ScriptedPrompter:
    """Strictly ordered answers; any question that is not next in the script fails the test."""

    def __init__(self, script: list[tuple[str, str, Answer]]) -> None:
        self.script = list(script)
        self.said: list[str] = []
        self.asked: list[str] = []

    def _next(self, kind: str, question: str) -> Answer:
        self.asked.append(f"{kind}: {question}")
        assert self.script, f"unexpected {kind}: {question!r}"
        want_kind, fragment, answer = self.script.pop(0)
        assert (want_kind, fragment in question) == (kind, True), (
            f"expected {want_kind} containing {fragment!r}, got {kind}: {question!r}"
        )
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def ask(self, question: str, default: str = "") -> str:
        answer = self._next("ask", question)
        if callable(answer):
            return answer()
        assert isinstance(answer, str)
        return default if answer == "<default>" else answer

    def secret(self, question: str) -> str:
        answer = self._next("secret", question)
        assert isinstance(answer, str)
        return answer

    def confirm(self, question: str, default: bool = True) -> bool:
        answer = self._next("confirm", question)
        assert isinstance(answer, bool)
        return answer

    def say(self, text: str) -> None:
        self.said.append(text)


class Harness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.server_dir = tmp_path / "server"
        self.server_dir.mkdir()
        self.db_path = tmp_path / "agent.db"
        monkeypatch.setenv("PERSONALAI_DB_PATH", str(self.db_path))
        self.system = FakeSystem(self.server_dir)
        self.keystore = KeyStore()
        self.client_json = tmp_path / "client.json"
        self.client_json.write_text("{}")
        self.doctor_calls = 0
        self.pairing_calls = 0

    def doctor(self) -> int:
        self.doctor_calls += 1
        return 0

    def open_pairing(self) -> None:
        self.pairing_calls += 1

    def start_server(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE devices (id TEXT, name TEXT, revoked INTEGER DEFAULT 0)")
        conn.commit()
        conn.close()

    def pair_phone(self) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO devices (id, name) VALUES ('d1', 'phone')")
        conn.commit()
        conn.close()
        return ""

    def fix_power(self) -> str:
        self.system.power_ok = True
        return ""

    def run(
        self, script: list[tuple[str, str, Answer]], redo: Sequence[str] = ()
    ) -> tuple[int, ScriptedPrompter]:
        prompter = ScriptedPrompter(script)
        code = run_setup(
            self.system,
            prompter,
            self.keystore,
            server_dir=self.server_dir,
            run_doctor=self.doctor,
            open_pairing=self.open_pairing,
            redo=redo,
        )
        assert prompter.script == [], f"unused answers: {prompter.script}"
        return code, prompter

    def first_run_script(self) -> list[tuple[str, str, Answer]]:
        return [
            ("confirm", "uv sync", True),
            ("secret", "NVIDIA API key", KEY),
            ("confirm", "Store the key", True),
            ("secret", "Tavily API key", TAVILY_KEY),
            ("confirm", "Store the key", True),
            ("confirm", "eval_models", True),
            ("ask", "Model ids to evaluate", "vendor/model-a,vendor/model-b"),
            ("ask", "PRIMARY", "vendor/model-a"),
            ("ask", "FALLBACK", "vendor/model-b"),
            ("ask", "LONG-context model", ""),
            ("ask", "token limit", "48000"),
            ("confirm", "model settings", True),
            ("confirm", "Pull the Ollama model", True),
            ("ask", "Local context size", "8192"),
            ("confirm", "context settings", True),
            ("confirm", "Add or update", True),
            ("ask", "Google account address", "ME@example.com"),
            ("ask", "Services", "gmail,calendar"),
            ("ask", "OAuth client JSON", str(self.client_json)),
            ("confirm", "Sign in", True),
            ("confirm", "Use me@example.com", True),
            ("ask", "Google account address", "me@college.example.edu"),
            ("ask", "Services", "classroom,drive"),
            ("confirm", "Sign in", True),
            ("confirm", "Use me@college", True),
            ("ask", "Google account address", ""),
            ("ask", "email addresses", "<default>"),
            ("ask", "VIP", "boss@example.com"),
            ("ask", "College domains", "college.example.edu"),
            ("ask", "Folders", "C:\\Docs;C:\\Notes"),
            ("confirm", "Save your profile", True),
            ("confirm", "Bind the server", True),
            ("confirm", "Install the", True),
            ("confirm", "Start the task", True),
            ("ask", "Press Enter when done", self.fix_power),
            ("confirm", "pairing window", True),
            ("ask", "after pairing", self.pair_phone),
        ]

    def complete_first_run(self) -> None:
        self.start_server()
        code, _ = self.run(self.first_run_script())
        assert code == 0


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    for name in list(os.environ):
        if name.startswith("PERSONALAI_") or name == "OLLAMA_CONTEXT_LENGTH":
            monkeypatch.delenv(name)
    return Harness(tmp_path, monkeypatch)


def test_first_run_on_blank_machine(harness: Harness) -> None:
    harness.start_server()
    code, prompter = harness.run(harness.first_run_script())

    assert code == 0
    assert harness.doctor_calls == 1
    assert harness.pairing_calls == 1
    s = harness.server_dir
    assert harness.system.interactive == [
        ["uv", "sync", "--directory", str(s)],
        [
            "uv", "run", "--directory", str(s), "python", "scripts/eval_models.py",
            "vendor/model-a", "vendor/model-b",
        ],
        ["ollama", "pull", "qwen2.5:3b"],
        [
            "uv", "run", "--directory", str(s), "python", "scripts/setup_google_oauth.py",
            "--account", "me@example.com", "--services", "gmail,calendar",
            "--client-secret", str(harness.client_json),
        ],
        [
            "uv", "run", "--directory", str(s), "python", "scripts/setup_google_oauth.py",
            "--account", "me@college.example.edu", "--services", "classroom,drive",
        ],
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(s / "scripts" / "install_task.ps1"),
        ],
    ]  # fmt: skip
    # Started through restart_server (schtasks /Run), never a bare Start-ScheduledTask.
    assert ["schtasks", "/Run", "/TN", "PersonalAi agent"] in harness.system.runs
    assert dict(harness.system.env) == {
        "PERSONALAI_MODEL_PRIMARY": "vendor/model-a",
        "PERSONALAI_MODEL_FALLBACK": "vendor/model-b",
        "PERSONALAI_LONG_CONTEXT_TOKENS": "48000",
        "PERSONALAI_LOCAL_CONTEXT_TOKENS": "8192",
        "OLLAMA_CONTEXT_LENGTH": "8192",
        "PERSONALAI_MAIL_ACCOUNTS": "me@example.com",
        "PERSONALAI_CALENDAR_ACCOUNTS": "me@example.com",
        "PERSONALAI_CLASSROOM_ACCOUNTS": "me@college.example.edu",
        "PERSONALAI_DRIVE_ACCOUNTS": "me@college.example.edu",
        "PERSONALAI_OWNER_EMAILS": "me@example.com,me@college.example.edu",
        "PERSONALAI_VIP_SENDERS": "boss@example.com",
        "PERSONALAI_COLLEGE_DOMAINS": "college.example.edu",
        "PERSONALAI_FILE_ROOTS": "C:\\Docs;C:\\Notes",
        "PERSONALAI_BIND_HOSTS": f"127.0.0.1,{TAILSCALE_IP}",
    }
    assert harness.keystore.get("nvidia_api_key") == KEY
    assert harness.keystore.get("tavily_api_key") == TAVILY_KEY
    assert any("delete the downloaded client json" in t.lower() for t in prompter.said)


def test_key_never_leaks(harness: Harness) -> None:
    harness.start_server()
    _, prompter = harness.run(harness.first_run_script())
    system = harness.system

    assert not any(KEY in part for argv in system.interactive + system.runs for part in argv)
    assert not any(KEY in name or KEY in value for name, value in system.set_calls)
    assert not any(KEY in text for text in prompter.said + prompter.asked)
    assert not any(TAVILY_KEY in text for text in prompter.said + prompter.asked)
    assert not any(KEY in value for value in os.environ.values())
    assert system.headers  # the key was used, but only in the request header


def test_second_run_is_idempotent(harness: Harness) -> None:
    harness.complete_first_run()
    system = harness.system
    system.interactive.clear()
    system.set_calls.clear()

    code, prompter = harness.run([("confirm", "Add or update", False)])

    assert code == 0
    assert system.interactive == []
    assert system.set_calls == []
    assert harness.doctor_calls == 2
    assert harness.pairing_calls == 1
    done = [t for t in prompter.said if t.startswith("✓")]
    assert len(done) >= 8


def test_redo_reruns_only_that_step(harness: Harness) -> None:
    harness.complete_first_run()
    system = harness.system
    system.interactive.clear()
    system.set_calls.clear()

    code, _ = harness.run(
        [
            ("confirm", "Add or update", False),
            ("confirm", "Bind the server", True),
            ("confirm", "restart the task", False),
        ],
        redo=["network"],
    )

    assert code == 0
    assert system.set_calls == [("PERSONALAI_BIND_HOSTS", f"127.0.0.1,{TAILSCALE_IP}")]
    assert system.interactive == []


def test_tavily_key_is_optional_and_redoable(harness: Harness) -> None:
    harness.complete_first_run()
    assert harness.keystore.get("tavily_api_key") == TAVILY_KEY
    # Already stored: not asked again unless the step is redone.
    harness.system.interactive.clear()
    code, prompter = harness.run([("confirm", "Add or update", False)])
    assert code == 0
    assert any("Tavily API key: already done" in t for t in prompter.said)
    # Redo with an odd-looking key: warned, then replaced.
    code, prompter = harness.run(
        [
            ("secret", "Tavily API key", "not-a-tavily-key"),
            ("confirm", "Store the key", True),
            ("confirm", "Add or update", False),
        ],
        redo=["tavily_key"],
    )
    assert code == 0
    assert any("tvly-" in t for t in prompter.said)
    assert harness.keystore.get("tavily_api_key") == "not-a-tavily-key"
    assert not any("not-a-tavily-key" in t for t in prompter.said + prompter.asked)


def test_unknown_redo_step_is_refused(harness: Harness) -> None:
    code, prompter = harness.run([], redo=["nope"])
    assert code == 2
    assert any("Unknown step" in t for t in prompter.said)


def test_declining_every_confirmation_changes_nothing(harness: Harness) -> None:
    script: list[tuple[str, str, Answer]] = [
        ("confirm", "uv sync", False),
        ("secret", "NVIDIA API key", KEY),
        ("confirm", "Store the key", False),
        ("secret", "Tavily API key", ""),
        ("confirm", "Pull the Ollama model", False),
        ("ask", "Local context size", "8192"),
        ("confirm", "context settings", False),
        ("confirm", "Add or update", False),
        ("ask", "email addresses", "me@example.com"),
        ("ask", "VIP", ""),
        ("ask", "College domains", ""),
        ("ask", "Folders", ""),
        ("confirm", "Save your profile", False),
        ("confirm", "Bind the server", False),
        ("confirm", "Install the", False),
        ("ask", "Press Enter when done", ""),
    ]
    code, _ = harness.run(script)

    assert code == 0
    assert harness.system.interactive == []
    assert harness.system.set_calls == []
    assert harness.keystore.get("nvidia_api_key") is None
    assert harness.pairing_calls == 0


def test_not_windows_is_refused(harness: Harness) -> None:
    harness.system.platform = "linux"
    code, prompter = harness.run([])
    assert code == 2
    assert any("SETUP.md" in t for t in prompter.said)
    assert harness.system.interactive == []


@pytest.mark.parametrize("stop", [EOFError(), KeyboardInterrupt()])
def test_eof_or_interrupt_stops_cleanly(harness: Harness, stop: BaseException) -> None:
    code, prompter = harness.run([("confirm", "uv sync", stop)])
    assert code == 1
    assert any("run it again" in t for t in prompter.said)
    assert harness.doctor_calls == 0


def test_power_step_never_changes_settings(harness: Harness) -> None:
    harness.complete_first_run()
    system = harness.system
    system.power_ok = False

    code, prompter = harness.run(
        [("confirm", "Add or update", False), ("ask", "Press Enter when done", "")],
        redo=[],
    )

    assert code == 0
    assert any("never changes power settings" in t for t in prompter.said)
    every = system.runs + system.interactive
    assert not any(flag in argv for argv in every for flag in FORBIDDEN_POWER)
    assert not any(argv[0] == "powercfg" and "/qh" not in argv for argv in every)


def test_google_merge_has_no_duplicates(harness: Harness) -> None:
    harness.complete_first_run()
    system = harness.system
    system.interactive.clear()
    system.set_calls.clear()

    script: list[tuple[str, str, Answer]] = [
        ("confirm", "Add or update", True),
        ("ask", "Google account address", "Me@Example.com"),
        ("ask", "Services", "gmail,calendar"),
        ("confirm", "Sign in", True),
        ("ask", "Google account address", "other@example.com"),
        ("ask", "Services", "gmail,drive"),
        ("confirm", "Sign in", True),
        ("confirm", "Use other@example.com", True),
        ("ask", "Google account address", ""),
        ("confirm", "restart the task", False),
    ]
    code, _ = harness.run(script, redo=["google"])

    assert code == 0
    assert dict(system.set_calls) == {
        "PERSONALAI_MAIL_ACCOUNTS": "me@example.com,other@example.com",
        "PERSONALAI_DRIVE_ACCOUNTS": "me@college.example.edu,other@example.com",
    }
    assert all("--client-secret" not in argv for argv in system.interactive)


def test_task_restart_offered_when_settings_changed(harness: Harness) -> None:
    harness.complete_first_run()
    system = harness.system
    system.interactive.clear()
    system.runs.clear()
    system.env.pop("PERSONALAI_BIND_HOSTS")

    code, _ = harness.run(
        [
            ("confirm", "Add or update", False),
            ("confirm", "Bind the server", True),
            ("confirm", "restart the task", True),
        ]
    )

    assert code == 0
    assert system.interactive == []
    # Ended through the scheduler, then started again: the shared restart path.
    task_calls = [r[1] for r in system.runs if r[0] == "schtasks" and r[1] != "/Query"]
    assert task_calls == ["/End", "/Run"]


def test_bad_nvidia_listing_skips_models_without_leaking(harness: Harness) -> None:
    class DownSystem(FakeSystem):
        def http_get(self, url: str, **kwargs: Any) -> HttpResult:
            if url.endswith("/api/tags"):
                return super().http_get(url, **kwargs)
            return HttpResult(401)

    harness.system = DownSystem(harness.server_dir)
    harness.start_server()
    script: list[tuple[str, str, Answer]] = [
        ("confirm", "uv sync", False),
        ("secret", "NVIDIA API key", KEY),
        ("confirm", "Store the key", True),
        ("secret", "Tavily API key", ""),
        ("confirm", "Pull the Ollama model", False),
        ("ask", "Local context size", "8192"),
        ("confirm", "context settings", False),
        ("confirm", "Add or update", False),
        ("ask", "email addresses", ""),
        ("confirm", "Bind the server", False),
        ("confirm", "Install the", False),
        ("ask", "Press Enter when done", ""),
        ("confirm", "pairing window", False),
    ]
    code, prompter = harness.run(script)

    assert code == 0
    assert any("401" in t for t in prompter.said)
    assert not any(KEY in t for t in prompter.said)
