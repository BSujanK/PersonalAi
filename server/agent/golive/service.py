"""Finding, stopping and starting the running server (``agent restart``, ``agent doctor``).

Everything goes through :class:`~agent.golive.system.System`, so tests drive it with a fake and
never touch the real scheduler or processes. Windows only: process discovery uses CIM and the
scheduled task is the one ``scripts/install_task.ps1`` registers.

Why this exists: stopping the scheduled task kills only its launcher. The task now ties the
server to its supervisor (``agent supervise``, a job object), but a server started by an older
install, or by hand in a terminal, can still be left running with stale code and the port taken, so
the next start exits with code 3. ``restart`` stops every ``agent serve`` of this user, waits until
the task is idle and the port is free, then starts the task and checks that a new server logged
itself.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TextIO

from agent.config import Settings
from agent.golive import probes
from agent.golive.system import System

# ``python -m agent`` and ``python -m agent serve`` both run the server (serve is the default).
_SERVE_CMD = re.compile(r"(?:^|\s)-m\s+agent(?:\s+serve)?\s*$")
_RUNNERS = ("python.exe", "pythonw.exe", "uv.exe")

STOP_TIMEOUT_SECONDS = 15.0
START_TIMEOUT_SECONDS = 20.0
POLL_SECONDS = 0.5
MAX_RUNS = 2  # the first ``schtasks /Run`` and one retry
SERVER_STARTED = "server started pid="  # written to agent.log by the supervisor

# Only this user's session, only interpreters and uv; the command line is matched in Python, so
# this script itself (a powershell.exe) can never match. Output is one compact JSON array.
_LIST_SCRIPT = (
    "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
    "$sid = (Get-Process -Id $PID).SessionId; "
    "$found = @(Get-CimInstance Win32_Process | "
    "Where-Object { $_.SessionId -eq $sid -and $_.Name -in 'python.exe','pythonw.exe','uv.exe' } | "
    "ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; ppid = $_.ParentProcessId; "
    "name = $_.Name; "
    "started = $_.CreationDate.ToUniversalTime().ToString('o'); cmd = $_.CommandLine } }); "
    "ConvertTo-Json -InputObject $found -Compress"
)
LIST_PROCESSES = ("powershell", "-NoProfile", "-NonInteractive", "-Command", _LIST_SCRIPT)


@dataclass(frozen=True)
class ServerProcess:
    pid: int
    ppid: int
    name: str
    started: datetime  # timezone-aware UTC


def _parse_started(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def find_server_processes(system: System) -> list[ServerProcess] | None:
    """Every running ``agent serve`` of this user (launchers included); ``None`` if unreadable."""
    if system.platform != "win32":
        return None
    result = system.run(LIST_PROCESSES, timeout=60)
    if result.returncode != 0:
        return None
    try:
        rows = json.loads(result.stdout.strip() or "[]")
    except ValueError:
        return None
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return None
    found: list[ServerProcess] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("name", "")).lower() not in _RUNNERS:
            continue
        command = row.get("cmd")
        started = _parse_started(row.get("started"))
        pid, ppid = row.get("pid"), row.get("ppid")
        if (
            not isinstance(command, str)
            or not _SERVE_CMD.search(command.strip())
            or started is None
            or not isinstance(pid, int)
            or not isinstance(ppid, int)
        ):
            continue
        found.append(ServerProcess(pid, ppid, str(row["name"]), started))
    return found


def newest_source_mtime(code_dir: Path) -> datetime | None:
    """When the newest ``*.py`` under ``code_dir`` was last modified (UTC), if any."""
    newest = 0.0
    for path in code_dir.rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(newest, UTC) if newest else None


def _roots(procs: Sequence[ServerProcess]) -> list[ServerProcess]:
    """Processes whose parent is not itself a server process; killing their trees kills all."""
    pids = {p.pid for p in procs}
    return [p for p in procs if p.ppid not in pids]


def _say(out: TextIO, text: str) -> None:
    out.write(text + "\n")


def restart_server(
    system: System,
    out: TextIO,
    *,
    settings: Settings | None = None,
    task_name: str = probes.TASK_NAME,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    stop_timeout: float = STOP_TIMEOUT_SECONDS,
    start_timeout: float = START_TIMEOUT_SECONDS,
) -> int:
    """Stop every running server, start the scheduled task and confirm a new server came up.

    The server is only started once the old one is really gone: the task no longer reports
    ``Running`` and the port is free on every bind address. Starting earlier is the race that
    makes the new server exit with code 3 (port taken). A start is confirmed by a new
    ``server started`` line in ``agent.log``; if none shows up, the task is run once more.
    Returns the exit code (0 only when a new server is confirmed).
    """
    config = settings if settings is not None else Settings()
    if system.platform != "win32":
        _say(out, "restart is only available on Windows (the server runs from a scheduled task).")
        return 1
    if find_server_processes(system) is None:
        _say(out, "Could not list running processes, so nothing was stopped.")
        return 1
    task = probes.scheduled_task(system, task_name)
    if task.exists:
        # Stop through the scheduler first so it does not restart the server behind our back.
        system.run(["schtasks", "/End", "/TN", task_name])
    running = find_server_processes(system) or []
    for proc in _roots(running):
        system.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"])
    if running:
        _say(out, f"Stopped {len(running)} server process(es).")

    blockers: list[str] = []

    def stopped() -> bool:
        blockers[:] = _stop_blockers(system, task_name, task.exists, config)
        return not blockers

    if not _wait_until(stopped, clock, sleep, stop_timeout):
        _say(out, f"The old server did not stop in {stop_timeout:.0f}s: {'; '.join(blockers)}.")
        _say(out, "End it in Task Manager, then run restart again.")
        return 1
    if not task.exists:
        _say(out, f'The task "{task_name}" is not installed, so nothing was started.')
        _say(out, "Install it: powershell -ExecutionPolicy Bypass -File scripts\\install_task.ps1")
        return 1
    log_path = config.db_path.parent / "agent.log"
    reason = ""
    for attempt in range(MAX_RUNS):
        offset = system.file_size(log_path)
        started = system.run(["schtasks", "/Run", "/TN", task_name])
        if started.returncode != 0:
            _say(out, f'Could not start the task "{task_name}".')
            return 1
        up = partial(_new_server_up, system, log_path, offset)
        confirmed = _wait_until(up, clock, sleep, start_timeout)
        if confirmed:
            _say(out, f'Restarted "{task_name}". Check it with: uv run python -m agent doctor')
            return 0
        reason = (
            f"no new 'server started' line in agent.log within {start_timeout:.0f}s "
            "(or the server exited again)"
        )
        if attempt + 1 < MAX_RUNS:
            _say(out, "No sign of the new server yet; starting the task once more.")
    _say(out, f"The server did not start: {reason}.")
    _say(out, "Run: uv run python -m agent doctor")
    return 1


def _stop_blockers(
    system: System, task_name: str, task_exists: bool, config: Settings
) -> list[str]:
    """What still prevents a clean start: a server process, a running task or a taken port."""
    blockers: list[str] = []
    if find_server_processes(system):
        blockers.append("a server process is still running")
    if task_exists and probes.scheduled_task(system, task_name).status == "Running":
        blockers.append(f'the task "{task_name}" still reports Running')
    busy = [h for h in config.bind_hosts if not system.port_is_free(h, config.port)]
    if busy:
        blockers.append(f"port {config.port} is still in use on {', '.join(busy)}")
    return blockers


def _new_server_up(system: System, log_path: Path, offset: int) -> bool:
    """A ``server started`` line written after ``offset`` and a server process that is alive."""
    size = system.file_size(log_path)
    text = system.read_text_from(log_path, offset if size >= offset else 0)  # rotated: reread
    return SERVER_STARTED in text and bool(find_server_processes(system))


def _wait_until(
    condition: Callable[[], bool],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    seconds: float,
) -> bool:
    """Poll ``condition`` until it holds or ``seconds`` pass (one last check at the deadline)."""
    deadline = clock() + seconds
    while True:
        if condition():
            return True
        if clock() >= deadline:
            return False
        sleep(POLL_SECONDS)
