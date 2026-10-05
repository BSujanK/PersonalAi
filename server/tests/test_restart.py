from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.config import Settings
from agent.golive import probes
from agent.golive.restart import log_path, restart_server
from agent.golive.system import NOT_FOUND, CommandResult, HttpResult

SERVER_CMD = "C:\\app\\server\\.venv\\Scripts\\pythonw.exe -m agent serve"
STARTED = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)


def _listener_output(pid: int, cmd: str, started: str = "2026-10-05T11:00:00.1234567Z") -> str:
    return json.dumps({"pid": pid, "started": started, "cmd": cmd})


class FakeMachine:
    """A tiny Windows: one task, one port, and the commands that change them."""

    platform = "win32"

    def __init__(self) -> None:
        self.task_exists = True
        self.holder: tuple[int, str] | None = (100, SERVER_CMD)
        self.after_start: tuple[int, str] | None = (200, SERVER_CMD)
        self.port_frees_on_stop = False
        self.kill_frees_port = True
        self.start_code = 0
        self.log: list[str] = []

    def python_version(self) -> tuple[int, int, int]:
        return (3, 12, 0)

    def which(self, name: str) -> str | None:
        return name

    def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
        if argv[0] == "schtasks":
            return CommandResult(0 if self.task_exists else 1, "Status: Ready\n")
        if argv[0] == "taskkill":
            self.log.append("kill " + argv[2])
            if self.kill_frees_port:
                self.holder = None
            return CommandResult(0, "")
        if argv[0] == "powershell":
            script = argv[-1]
            if script.startswith("Stop-ScheduledTask"):
                self.log.append("stop")
                if self.port_frees_on_stop:
                    self.holder = None
                return CommandResult(0, "")
            if script.startswith("Start-ScheduledTask"):
                self.log.append("start")
                self.holder = self.after_start
                return CommandResult(self.start_code, "")
            if "Get-NetTCPConnection" in script:
                if self.holder is None:
                    return CommandResult(0, "")
                return CommandResult(0, _listener_output(*self.holder))
        return CommandResult(NOT_FOUND, "")

    def run_interactive(self, argv: Sequence[str]) -> int:
        raise AssertionError("restart must not run interactive commands")

    def http_get(
        self, url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10
    ) -> HttpResult:
        raise AssertionError("restart must not use the network")

    def user_env(self, name: str) -> str | None:
        return None

    def set_user_env(self, name: str, value: str) -> None:
        raise AssertionError("restart must not change the environment")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


def _restart(machine: FakeMachine, tmp_path: Path) -> tuple[int, list[str], Clock]:
    settings = Settings(db_path=tmp_path / "agent.db")
    clock = Clock()
    lines: list[str] = []
    code = restart_server(
        machine, settings, out=lines.append, sleep=clock.sleep, monotonic=clock.monotonic
    )
    return code, lines, clock


# --- probes ----------------------------------------------------------------------------------


def _system(output: str, code: int = 0) -> FakeMachine:
    machine = FakeMachine()
    machine.run = lambda argv, *, timeout=30: CommandResult(code, output)  # type: ignore[method-assign]
    return machine


def test_listener_parses_compact_json() -> None:
    found = probes.listener(_system(_listener_output(4242, SERVER_CMD)), 8765)
    assert found == probes.ListenerInfo(4242, STARTED.replace(microsecond=123456), SERVER_CMD)
    assert found is not None and found.started_at.utcoffset() is not None


def test_listener_treats_missing_command_line_as_empty() -> None:
    output = json.dumps({"pid": 5, "started": "2026-10-05T11:00:00Z", "cmd": None})
    found = probes.listener(_system(output), 8765)
    assert found is not None and found.command_line == ""


@pytest.mark.parametrize(
    "output",
    [
        "",
        "   \n",
        "not json",
        "[]",
        "null",
        json.dumps({"pid": "x", "started": "2026-10-05T11:00:00Z"}),
        json.dumps({"pid": True, "started": "2026-10-05T11:00:00Z"}),
        json.dumps({"pid": 1, "started": "yesterday"}),
        json.dumps({"pid": 1}),
        json.dumps({"pid": 1, "started": "2026-10-05T11:00:00Z", "cmd": 5}),
    ],
)
def test_listener_garbage_is_none(output: str) -> None:
    assert probes.listener(_system(output), 8765) is None


def test_listener_failed_command_is_none() -> None:
    assert probes.listener(_system(_listener_output(1, SERVER_CMD), code=1), 8765) is None


def test_task_executable() -> None:
    assert probes.task_executable(_system("C:\\x\\pythonw.exe\r\n")) == "C:\\x\\pythonw.exe"
    assert probes.task_executable(_system("")) is None
    assert probes.task_executable(_system("boom", code=1)) is None


@pytest.mark.parametrize(
    ("command_line", "expected"),
    [
        (SERVER_CMD, True),
        ('"C:\\Program Files\\py\\python.exe" -m agent', True),
        ("python -m agent serve", True),
        ("python -m agent pair", False),
        ("python -m agent doctor --json", False),
        ("python -m http.server 8765", False),
        ("python -m agent", True),
        ("node server.js", False),
        ("python -m", False),
        ("", False),
        ('python -m agent "unclosed', False),
    ],
)
def test_is_agent_server(command_line: str, expected: bool) -> None:
    assert probes.is_agent_server(command_line) is expected


def test_newest_code_mtime(tmp_path: Path) -> None:
    assert probes.newest_code_mtime(tmp_path) is None
    (tmp_path / "agent" / "sub").mkdir(parents=True)
    old, mid, new = (datetime(2026, 10, d, tzinfo=UTC) for d in (1, 2, 3))
    for path, moment in (
        (tmp_path / "agent" / "a.py", old),
        (tmp_path / "agent" / "sub" / "b.py", mid),
        (tmp_path / "agent" / "notes.txt", new),
        (tmp_path / "other.py", new),
    ):
        path.write_text("x", encoding="utf-8")
        os.utime(path, (moment.timestamp(), moment.timestamp()))
    assert probes.newest_code_mtime(tmp_path) == mid
    lock = tmp_path / "uv.lock"
    lock.write_text("x", encoding="utf-8")
    os.utime(lock, (new.timestamp(), new.timestamp()))
    assert probes.newest_code_mtime(tmp_path) == new


# --- restart ---------------------------------------------------------------------------------


def test_restart_kills_stale_agent_server_and_starts_new_one(tmp_path: Path) -> None:
    machine = FakeMachine()
    code, lines, _ = _restart(machine, tmp_path)
    assert code == 0
    assert machine.log == ["stop", "kill 100", "start"]
    assert lines[-1] == "Server restarted (pid 200)."


def test_restart_waits_for_port_to_free_then_starts(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.holder = None
    code, lines, _ = _restart(machine, tmp_path)
    assert code == 0
    assert machine.log == ["stop", "start"]
    assert lines == ["Server restarted (pid 200)."]


def test_restart_does_not_kill_a_foreign_listener(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.holder = (77, "C:\\other\\thing.exe --listen 8765")
    code, lines, _ = _restart(machine, tmp_path)
    assert code == 1
    assert machine.log == ["stop"]
    assert "pid 77" in lines[0] and "8765" in lines[0]


def test_restart_gives_up_when_port_never_frees(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.kill_frees_port = False
    code, lines, clock = _restart(machine, tmp_path)
    assert code == 1
    assert "start" not in machine.log
    assert "still in use" in lines[-1]
    assert 15 <= clock.now < 16


def test_restart_reports_when_server_never_comes_back(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.after_start = None
    code, lines, clock = _restart(machine, tmp_path)
    assert code == 1
    assert 30 <= clock.now < 31
    assert str(log_path(Settings(db_path=tmp_path / "agent.db"))) in lines[-1]
    assert "agent doctor" in lines[-1]


def test_restart_does_not_accept_a_foreign_process_as_the_new_server(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.after_start = (300, "C:\\other\\thing.exe")
    code, _, _ = _restart(machine, tmp_path)
    assert code == 1


def test_restart_reports_start_failure(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.start_code = 1
    code, lines, _ = _restart(machine, tmp_path)
    assert code == 1
    assert "failed" in lines[-1]


def test_restart_off_windows_does_nothing(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.platform = "linux"
    code, lines, _ = _restart(machine, tmp_path)
    assert code == 2
    assert machine.log == []
    assert "agent serve" in lines[0]


def test_restart_without_task_prints_install_fix(tmp_path: Path) -> None:
    machine = FakeMachine()
    machine.task_exists = False
    code, lines, _ = _restart(machine, tmp_path)
    assert code == 1
    assert machine.log == []
    assert "install_task.ps1" in lines[1]


def test_log_path_sits_next_to_the_database(tmp_path: Path) -> None:
    assert log_path(Settings(db_path=tmp_path / "agent.db")) == tmp_path / "agent.log"
