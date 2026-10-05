"""Finding, stopping and starting the running server (``agent restart``, ``agent doctor``).

Everything goes through :class:`~agent.golive.system.System`, so tests drive it with a fake and
never touch the real scheduler or processes. Windows only: process discovery uses CIM and the
scheduled task is the one ``scripts/install_task.ps1`` registers.

Why this exists: stopping the scheduled task kills only its PowerShell host. The task now ties the
server to that host (``scripts/run_agent.ps1``), but a server started by an older install, or by
hand in a terminal, can still be left running with stale code and the port taken, so the next
start exits with code 3. ``restart`` stops every ``agent serve`` of this user, then starts the task.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from agent.golive import probes
from agent.golive.system import System

# ``python -m agent`` and ``python -m agent serve`` both run the server (serve is the default).
_SERVE_CMD = re.compile(r"(?:^|\s)-m\s+agent(?:\s+serve)?\s*$")
_RUNNERS = ("python.exe", "pythonw.exe", "uv.exe")

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
    task_name: str = probes.TASK_NAME,
    sleep: Callable[[float], None] = time.sleep,
    wait_seconds: int = 20,
) -> int:
    """Stop every running server and start the scheduled task. Returns the exit code."""
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

    def stopped() -> bool:
        if find_server_processes(system):
            return False
        return not task.exists or probes.scheduled_task(system, task_name).status != "Running"

    if not _wait_until(stopped, sleep, wait_seconds):
        _say(out, "The server is still running after being stopped; end it in Task Manager.")
        return 1
    if not task.exists:
        _say(out, f'The task "{task_name}" is not installed, so nothing was started.')
        _say(out, "Install it: powershell -ExecutionPolicy Bypass -File scripts\\install_task.ps1")
        return 1
    started = system.run(["schtasks", "/Run", "/TN", task_name])
    if started.returncode != 0:
        _say(out, f'Could not start the task "{task_name}".')
        return 1
    if not _wait_until(lambda: bool(find_server_processes(system)), sleep, wait_seconds):
        _say(
            out, "The task started but no server is running yet. Run: uv run python -m agent doctor"
        )
        return 1
    _say(out, f'Restarted "{task_name}". Check it with: uv run python -m agent doctor')
    return 0


def _wait_until(
    condition: Callable[[], bool], sleep: Callable[[float], None], seconds: int
) -> bool:
    for _ in range(max(seconds, 1)):
        if condition():
            return True
        sleep(1)
    return condition()
