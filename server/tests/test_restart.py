"""``agent restart`` and the process discovery behind it, over a fake System.

Nothing here touches the real scheduler or kills real processes; the Windows-only smoke tests at
the end spawn and kill only their own throwaway process.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import agent.main as main_module
from agent.config import Settings
from agent.golive.probes import TASK_NAME
from agent.golive.service import (
    LIST_PROCESSES,
    MAX_RUNS,
    find_server_processes,
    restart_server,
)
from agent.golive.system import NOT_FOUND, CommandResult, HttpResult, RealSystem

STAMP = "2026-10-05T19:43:38.4232370Z"


def _row(pid: int, ppid: int, name: str, cmd: str, started: str = STAMP) -> dict[str, Any]:
    return {"pid": pid, "ppid": ppid, "name": name, "started": started, "cmd": cmd}


def _server_tree(base: int = 10) -> list[dict[str, Any]]:
    """uv -> venv launcher -> interpreter, as `uv run python -m agent serve` leaves behind."""
    return [
        _row(base, 1, "uv.exe", '"uv.exe" run --directory C:\\x python -m agent serve'),
        _row(base + 1, base, "python.exe", '"C:\\x\\.venv\\Scripts\\python.exe" -m agent serve'),
        _row(base + 2, base + 1, "python.exe", '"C:\\py\\python.exe"  -m agent serve'),
    ]


@dataclass
class SchedulerSystem:
    """A System whose process list and task state react to schtasks and taskkill."""

    platform: str = "win32"
    processes: list[dict[str, Any]] = field(default_factory=list)
    task_installed: bool = True
    task_status: str = "Running"
    # What starting the task brings up.
    on_run: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: _server_tree)
    # The /Run call (1-based) from which the new server comes up and logs "server started";
    # 0 means it never does.
    starts_on_run: int = 1
    # How many queries still see the task Running / the port taken after the old server is gone.
    task_running_polls: int = 0
    port_busy_polls: int = 0
    log_text: str = "supervisor started pid=1\nserver started pid=2 (the old one)\n"
    list_fails: bool = False
    stubborn: bool = False  # taskkill does not actually stop anything
    end_leaves_server: bool = False  # the old bug: /End kills the host only
    calls: list[tuple[str, ...]] = field(default_factory=list)
    port_checks: list[tuple[str, int]] = field(default_factory=list)

    def python_version(self) -> tuple[int, int, int]:
        return (3, 12, 4)

    def which(self, name: str) -> str | None:
        return None

    def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
        key = tuple(argv)
        self.calls.append(key)
        if key == LIST_PROCESSES:
            if self.list_fails:
                return CommandResult(1, "")
            return CommandResult(0, json.dumps(self.processes))
        if key[:2] == ("schtasks", "/Query"):
            if not self.task_installed:
                return CommandResult(1, "")
            if self.task_status == "Ready" and self.task_running_polls > 0:
                self.task_running_polls -= 1
                return CommandResult(0, f"TaskName: \\{TASK_NAME}\nStatus:        Running\n")
            return CommandResult(0, f"TaskName: \\{TASK_NAME}\nStatus:        {self.task_status}\n")
        if key[:2] == ("schtasks", "/End"):
            self.task_status = "Ready"
            if not self.end_leaves_server:
                self.processes = []
            return CommandResult(0, "")
        if key[:2] == ("schtasks", "/Run"):
            self.task_status = "Running"
            if 0 < self.starts_on_run <= len(self.commands("schtasks", "/Run")):
                self.processes = self.on_run()
                self.log_text += f"server started pid={len(self.log_text)}\n"
            return CommandResult(0, "")
        if key[0] == "taskkill":
            if not self.stubborn:
                self.processes = []
            return CommandResult(0, "")
        return CommandResult(NOT_FOUND, "")

    def run_interactive(self, argv: Sequence[str]) -> int:
        raise AssertionError("restart must not run interactive commands")

    def http_get(
        self, url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10
    ) -> HttpResult:
        raise AssertionError("restart must not use the network")

    def port_is_free(self, host: str, port: int) -> bool:
        self.port_checks.append((host, port))
        if self.port_busy_polls > 0:
            self.port_busy_polls -= 1
            return False
        return True

    def file_size(self, path: Path) -> int:
        return len(self.log_text.encode())

    def read_text_from(self, path: Path, offset: int) -> str:
        return self.log_text.encode()[offset:].decode()

    def user_env(self, name: str) -> str | None:
        return None

    def set_user_env(self, name: str, value: str) -> None:
        raise AssertionError("restart must not change the environment")

    def commands(self, program: str, subcommand: str | None = None) -> list[tuple[str, ...]]:
        return [
            c
            for c in self.calls
            if c[0] == program and (subcommand is None or (len(c) > 1 and c[1] == subcommand))
        ]


class FakeTime:
    """Monotonic clock whose sleep advances it, so bounded waits finish instantly."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _restart_timed(
    system: SchedulerSystem, settings: Settings | None = None
) -> tuple[int, str, FakeTime]:
    out = io.StringIO()
    fake = FakeTime()
    code = restart_server(system, out, settings=settings, sleep=fake.sleep, clock=fake.clock)
    return code, out.getvalue(), fake


def _restart(system: SchedulerSystem) -> tuple[int, str]:
    code, text, _ = _restart_timed(system)
    return code, text


# --- discovery -------------------------------------------------------------------------------


def test_finds_every_agent_serve_process_and_nothing_else() -> None:
    system = SchedulerSystem(
        processes=[
            *_server_tree(),
            _row(50, 1, "python.exe", "python.exe -m pytest"),
            _row(51, 1, "python.exe", "python.exe -m agent doctor"),
            _row(52, 1, "python.exe", "python.exe -m agent restart"),
            _row(53, 1, "python.exe", "python.exe -m agentx serve"),
            _row(54, 1, "powershell.exe", "powershell -m agent serve"),
            _row(55, 1, "python.exe", "python.exe -m agent"),  # `serve` is the default command
        ]
    )
    found = find_server_processes(system)
    assert found is not None
    assert [p.pid for p in found] == [10, 11, 12, 55]


def test_started_is_timezone_aware_utc() -> None:
    system = SchedulerSystem(processes=_server_tree())
    found = find_server_processes(system)
    assert found is not None and found[0].started.utcoffset() is not None
    assert found[0].started.isoformat().startswith("2026-10-05T19:43:38")


@pytest.mark.parametrize("output", ["", "[]", "null"])
def test_empty_output_means_no_server(output: str) -> None:
    class Quiet(SchedulerSystem):
        def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
            return CommandResult(0, output)

    result = find_server_processes(Quiet())
    assert result in ([], None)  # "null" is not a list: unreadable, never a crash


def test_a_single_process_is_a_json_object_not_a_list() -> None:
    class One(SchedulerSystem):
        def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
            return CommandResult(0, json.dumps(_server_tree()[1]))

    found = find_server_processes(One())
    assert found is not None and [p.pid for p in found] == [11]


def test_discovery_gives_up_off_windows_or_on_garbage() -> None:
    assert find_server_processes(SchedulerSystem(platform="linux")) is None
    assert find_server_processes(SchedulerSystem(list_fails=True)) is None

    class Garbage(SchedulerSystem):
        def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
            return CommandResult(0, "{not json")

    assert find_server_processes(Garbage()) is None


# --- restart ---------------------------------------------------------------------------------


def test_restart_stops_the_task_kills_leftovers_and_starts_the_task() -> None:
    system = SchedulerSystem(processes=_server_tree(), end_leaves_server=True)
    code, text = _restart(system)
    assert code == 0, text
    order = [c[:2] if c[0] == "schtasks" else (c[0],) for c in system.calls if c != LIST_PROCESSES]
    assert order.index(("schtasks", "/End")) < order.index(("taskkill",))
    assert order.index(("taskkill",)) < order.index(("schtasks", "/Run"))
    assert "Stopped 3 server process(es)" in text and "Restarted" in text
    assert system.processes  # the task brought a fresh server up


def test_restart_kills_only_tree_roots_with_the_whole_tree() -> None:
    system = SchedulerSystem(processes=_server_tree(), end_leaves_server=True)
    _restart(system)
    assert system.commands("taskkill") == [("taskkill", "/PID", "10", "/T", "/F")]


def test_restart_kills_a_server_started_by_hand_in_a_terminal() -> None:
    system = SchedulerSystem(
        processes=[_row(7, 1, "python.exe", "python.exe -m agent serve")],
        end_leaves_server=True,
        task_status="Ready",
    )
    code, _ = _restart(system)
    assert code == 0
    assert system.commands("taskkill") == [("taskkill", "/PID", "7", "/T", "/F")]


def test_restart_with_nothing_running_just_starts_the_task() -> None:
    system = SchedulerSystem(processes=[], task_status="Ready")
    code, text = _restart(system)
    assert code == 0 and "Stopped" not in text
    assert system.commands("taskkill") == []
    assert system.commands("schtasks", "/Run") == [("schtasks", "/Run", "/TN", TASK_NAME)]


def test_restart_stops_the_server_even_when_the_task_is_not_installed() -> None:
    system = SchedulerSystem(processes=_server_tree(), task_installed=False)
    code, text = _restart(system)
    assert code == 1
    assert system.processes == []  # the old server is gone
    assert system.commands("schtasks", "/Run") == []
    assert "not installed" in text and "install_task.ps1" in text


def test_restart_reports_a_server_that_will_not_die() -> None:
    system = SchedulerSystem(processes=_server_tree(), stubborn=True, end_leaves_server=True)
    code, text = _restart(system)
    assert code == 1 and "did not stop" in text and "server process is still running" in text
    assert system.commands("schtasks", "/Run") == []  # never start a second server on top


def test_restart_reports_a_task_that_starts_nothing() -> None:
    system = SchedulerSystem(processes=[], starts_on_run=0, task_status="Ready")
    code, text = _restart(system)
    assert code == 1 and "The server did not start" in text and "agent.log" in text


def test_restart_refuses_when_processes_cannot_be_listed() -> None:
    system = SchedulerSystem(processes=_server_tree(), list_fails=True)
    code, text = _restart(system)
    assert code == 1 and "nothing was stopped" in text
    assert system.commands("taskkill") == [] and system.commands("schtasks", "/End") == []


def test_restart_is_windows_only() -> None:
    system = SchedulerSystem(platform="linux", processes=_server_tree())
    code, text = _restart(system)
    assert code == 1 and "only available on Windows" in text
    assert system.calls == []


# --- the stop/start race ---------------------------------------------------------------------


def test_happy_path_waits_for_a_free_port_then_runs_once_and_confirms_in_the_log() -> None:
    system = SchedulerSystem(processes=_server_tree(), end_leaves_server=True)
    code, text, fake = _restart_timed(system)
    assert code == 0 and "Restarted" in text
    assert len(system.commands("schtasks", "/Run")) == 1
    assert system.port_checks == [("127.0.0.1", 8765)]
    assert fake.now < 1  # nothing had to wait


def test_checks_every_bind_address_on_the_configured_port() -> None:
    system = SchedulerSystem(processes=[])
    settings = Settings(bind_hosts=("127.0.0.1", "100.64.0.9"), port=9001)
    code, _, _ = _restart_timed(system, settings)
    assert code == 0
    assert system.port_checks == [("127.0.0.1", 9001), ("100.64.0.9", 9001)]


def test_port_still_busy_then_freed_delays_the_run() -> None:
    system = SchedulerSystem(processes=_server_tree(), port_busy_polls=4)
    code, text, fake = _restart_timed(system)
    assert code == 0, text
    assert fake.now >= 2  # it polled until the port was released
    assert len(system.commands("schtasks", "/Run")) == 1


def test_task_still_running_then_stopped_delays_the_run() -> None:
    system = SchedulerSystem(processes=[], task_running_polls=3)
    code, _, fake = _restart_timed(system)
    assert code == 0
    assert fake.now >= 1.5
    assert system.task_running_polls == 0  # every stale "Running" answer was consumed first


def test_port_that_never_frees_fails_without_running_the_task() -> None:
    system = SchedulerSystem(processes=[], port_busy_polls=10_000)
    code, text, fake = _restart_timed(system)
    assert code == 1
    assert "port 8765 is still in use on 127.0.0.1" in text
    assert system.commands("schtasks", "/Run") == []
    assert 15 <= fake.now < 16  # the stop wait is bounded at 15 s


def test_no_server_line_retries_once_and_then_succeeds() -> None:
    system = SchedulerSystem(processes=[], starts_on_run=2, task_status="Ready")
    code, text, fake = _restart_timed(system)
    assert code == 0, text
    assert len(system.commands("schtasks", "/Run")) == 2
    assert "once more" in text and "Restarted" in text
    assert 20 <= fake.now < 22  # one full 20 s start wait before the retry


def test_both_attempts_failing_gives_a_clear_reason_and_never_a_third_run() -> None:
    system = SchedulerSystem(processes=[], starts_on_run=0, task_status="Ready")
    code, text, fake = _restart_timed(system)
    assert code == 1
    assert len(system.commands("schtasks", "/Run")) == MAX_RUNS == 2
    assert "The server did not start" in text and "no new 'server started' line" in text
    assert 40 <= fake.now < 43


def test_an_old_server_line_in_the_log_does_not_count() -> None:
    system = SchedulerSystem(processes=[_row(7, 1, "python.exe", "python.exe -m agent serve")])
    system.starts_on_run = 0
    code, text, _ = _restart_timed(system)
    assert code == 1 and "The server did not start" in text  # the pre-existing line is ignored


def test_a_server_line_without_a_live_server_does_not_count() -> None:
    system = SchedulerSystem(processes=[], on_run=list, task_status="Ready")
    code, text, _ = _restart_timed(system)
    assert code == 1 and "server exited again" in text
    assert len(system.commands("schtasks", "/Run")) == 2


def test_a_rotated_log_is_read_from_the_start() -> None:
    class Rotating(SchedulerSystem):
        def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
            result = super().run(argv, timeout=timeout)
            if tuple(argv[:2]) == ("schtasks", "/Run"):
                self.log_text = "server started pid=9\n"  # shorter than before: rotated
            return result

    system = Rotating(processes=[], task_status="Ready", starts_on_run=1)
    system.log_text = "x" * 500
    code, text, _ = _restart_timed(system)
    assert code == 0, text


def test_a_failing_run_command_stops_without_a_retry() -> None:
    class Refusing(SchedulerSystem):
        def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
            if tuple(argv[:2]) == ("schtasks", "/Run"):
                self.calls.append(tuple(argv))
                return CommandResult(1, "")
            return super().run(argv, timeout=timeout)

    system = Refusing(processes=[], task_status="Ready")
    code, text = _restart(system)
    assert code == 1 and "Could not start the task" in text
    assert len(system.commands("schtasks", "/Run")) == 1


def test_restart_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_restart(system: object, out: object, *, settings: Settings, task_name: str) -> int:
        seen.append(task_name)
        return 0

    monkeypatch.setattr(main_module, "restart_server", fake_restart)
    assert main_module.main(["restart"]) == 0
    assert seen == [TASK_NAME]


# --- the real Windows machinery (only ever touches a throwaway child process) ----------------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows CIM and taskkill")


def _wait_for(condition: Callable[[], bool], seconds: float = 20) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.5)
    return condition()


@windows_only
def test_real_process_query_runs_and_parses() -> None:
    found = find_server_processes(RealSystem())
    assert found is not None  # the PowerShell/CIM script itself works on this machine


@windows_only
def test_real_discovery_and_taskkill_on_a_throwaway_process() -> None:
    # `-c CODE` ends python's own option parsing, so `-m agent serve` are plain argv here: the
    # process looks like a server to the command-line match but starts nothing.
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", "-m", "agent", "serve"]
    )
    system = RealSystem()
    try:
        assert _wait_for(
            lambda: child.pid in {p.pid for p in find_server_processes(system) or []}
        ), "the throwaway process was not found"
        system.run(["taskkill", "/PID", str(child.pid), "/T", "/F"])
        assert _wait_for(lambda: child.poll() is not None), "taskkill did not stop it"
        assert _wait_for(
            lambda: child.pid not in {p.pid for p in find_server_processes(system) or []}
        )
    finally:
        if child.poll() is None:
            child.kill()
