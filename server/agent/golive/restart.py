"""``agent restart``: stop the scheduled task, make sure the old server is really gone, start it.

Stopping the task alone is not enough if a stray server process still holds the port: the new one
fails to bind and the old one keeps serving stale code. So this frees the port first, but only
ever kills a process that is verifiably the agent server.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from agent.config import Settings
from agent.golive import probes
from agent.golive.system import System

EXIT_FAILED = 1
EXIT_UNSUPPORTED = 2
PORT_FREE_SECONDS = 15.0
SERVER_UP_SECONDS = 30.0
POLL_SECONDS = 0.5
INSTALL_FIX = "powershell -ExecutionPolicy Bypass -File scripts\\install_task.ps1"
RESTART_FIX = "uv run python -m agent restart"


def log_path(settings: Settings) -> Path:
    """Where the server writes its log when it has no console (pythonw)."""
    return settings.db_path.parent / "agent.log"


def _task_command(system: System, verb: str) -> int:
    script = f'{verb}-ScheduledTask -TaskName "{probes.TASK_NAME}"'
    return system.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    ).returncode


def restart_server(
    system: System,
    settings: Settings,
    *,
    out: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    if system.platform != "win32":
        out(
            "restart manages the Windows scheduled task. On other systems, stop and start "
            "`agent serve` yourself."
        )
        return EXIT_UNSUPPORTED
    if not probes.scheduled_task(system).exists:
        out(f'The scheduled task "{probes.TASK_NAME}" is not installed. Install it with:')
        out(f"  {INSTALL_FIX}")
        return EXIT_FAILED

    def poll[T](probe: Callable[[], T], seconds: float) -> T | None:
        """The first truthy result of ``probe`` within ``seconds``, else ``None``."""
        deadline = monotonic() + seconds
        while True:
            result = probe()
            if result:
                return result
            if monotonic() >= deadline:
                return None
            sleep(POLL_SECONDS)

    def port_free() -> bool:
        return probes.listener(system, settings.port) is None

    def agent_listener() -> probes.ListenerInfo | None:
        found = probes.listener(system, settings.port)
        return found if found is not None and probes.is_agent_server(found.command_line) else None

    _task_command(system, "Stop")
    stale = probes.listener(system, settings.port)
    if stale is not None:
        if not probes.is_agent_server(stale.command_line):
            out(
                f"Another program (pid {stale.pid}) holds port {settings.port}; "
                "not touching it. Stop it, then run restart again."
            )
            return EXIT_FAILED
        out(f"Stopping the old server (pid {stale.pid}).")
        if system.run(["taskkill", "/PID", str(stale.pid), "/T", "/F"]).returncode != 0:
            out(f"Could not stop pid {stale.pid}.")
            return EXIT_FAILED
    if not poll(port_free, PORT_FREE_SECONDS):
        out(f"Port {settings.port} is still in use after {PORT_FREE_SECONDS:.0f} seconds.")
        return EXIT_FAILED
    if _task_command(system, "Start") != 0:
        out("Starting the scheduled task failed.")
        return EXIT_FAILED
    server = poll(agent_listener, SERVER_UP_SECONDS)
    if server is None:
        out(
            f"The server did not come back within {SERVER_UP_SECONDS:.0f} seconds. "
            f"Check the log ({log_path(settings)}) and run `uv run python -m agent doctor`."
        )
        return EXIT_FAILED
    out(f"Server restarted (pid {server.pid}).")
    return 0
