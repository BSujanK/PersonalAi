"""Read-only probes shared by ``agent doctor`` and ``agent setup``. Nothing here changes state."""

from __future__ import annotations

import ipaddress
import json
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent.golive.system import System

TASK_NAME = "PersonalAi agent"
SERVER_DIR = Path(__file__).resolve().parents[2]
_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
_AC_INDEX = re.compile(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)")
_STATUS = re.compile(r"^\s*Status:\s*(.+?)\s*$", re.MULTILINE)

# The user runs these themselves; doctor and setup only print them.
POWER_FIX_COMMANDS = (
    "powercfg /change standby-timeout-ac 0",
    "powercfg /change hibernate-timeout-ac 0",
    "powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0",
    "powercfg /setactive SCHEME_CURRENT",
)


def tailscale_ipv4(system: System) -> list[str]:
    """This machine's Tailscale IPv4 addresses (``tailscale ip -4``); empty if none or no CLI."""
    result = system.run(["tailscale", "ip", "-4"])
    if result.returncode != 0:
        return []
    found: list[str] = []
    for line in result.stdout.splitlines():
        try:
            addr = ipaddress.ip_address(line.strip())
        except ValueError:
            continue
        if addr.version == 4 and addr in _TAILSCALE_V4:
            found.append(str(addr))
    return found


@dataclass(frozen=True)
class TaskState:
    exists: bool
    status: str | None = None  # "Running", "Ready", ... (English Windows); None if unreadable


def scheduled_task(system: System, name: str = TASK_NAME) -> TaskState:
    result = system.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"])
    if result.returncode != 0:
        return TaskState(exists=False)
    match = _STATUS.search(result.stdout)
    return TaskState(exists=True, status=match.group(1) if match else None)


def _powershell(system: System, script: str) -> str | None:
    """Stdout of a one-off PowerShell script, or ``None`` if it failed or printed nothing."""
    result = system.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    text = result.stdout.strip()
    return text if result.returncode == 0 and text else None


def task_executable(system: System, name: str = TASK_NAME) -> str | None:
    """The program the task's first action runs (``Execute``), or ``None`` if unreadable."""
    return _powershell(
        system,
        f'(Get-ScheduledTask -TaskName "{name}").Actions | '
        "Select-Object -First 1 -ExpandProperty Execute",
    )


@dataclass(frozen=True)
class ListenerInfo:
    pid: int
    started_at: datetime  # aware, UTC
    command_line: str  # may be empty when Windows hides it


def _listener_script(port: int) -> str:
    return (
        f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen "
        "-ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if (-not $c) { exit 0 }; "
        "$p = Get-Process -Id $c.OwningProcess -ErrorAction Stop; "
        '$w = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"; '
        "[pscustomobject]@{pid = $p.Id; "
        "started = $p.StartTime.ToUniversalTime().ToString('o'); "
        "cmd = $w.CommandLine} | ConvertTo-Json -Compress"
    )


def listener(system: System, port: int) -> ListenerInfo | None:
    """The process listening on ``port``; ``None`` if there is none or it could not be read."""
    output = _powershell(system, _listener_script(port))
    if output is None:
        return None
    try:
        data = json.loads(output)
        pid = data["pid"]
        started = datetime.fromisoformat(data["started"])
        command_line = data.get("cmd") or ""
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(command_line, str):
        return None
    started = started.replace(tzinfo=UTC) if started.tzinfo is None else started.astimezone(UTC)
    return ListenerInfo(pid, started, command_line)


def is_agent_server(command_line: str) -> bool:
    """True for ``... -m agent`` or ``... -m agent serve`` (serve is the default command)."""
    try:
        words = [w.strip("\"'") for w in shlex.split(command_line, posix=False)]
    except ValueError:
        return False
    for index, word in enumerate(words[:-1]):
        if word == "-m" and words[index + 1] == "agent":
            rest = words[index + 2 :]
            return not rest or rest[0] == "serve"
    return False


def newest_code_mtime(server_dir: Path) -> datetime | None:
    """Newest change time over the agent package's Python files and ``uv.lock``."""
    try:
        files = [*(server_dir / "agent").rglob("*.py"), server_dir / "uv.lock"]
        newest = max(f.stat().st_mtime for f in files if f.is_file())
    except (OSError, ValueError):
        return None
    return datetime.fromtimestamp(newest, UTC)


@dataclass(frozen=True)
class PowerSettings:
    """AC (plugged in) values; ``None`` when powercfg could not be read."""

    standby_ac: int | None  # seconds until sleep, 0 = never
    hibernate_ac: int | None  # seconds until hibernate, 0 = never
    lid_ac: int | None  # 0 = do nothing, 1 = sleep, 2 = hibernate, 3 = shut down

    @property
    def ok(self) -> bool:
        return self.standby_ac == 0 and self.hibernate_ac == 0 and self.lid_ac == 0


def _ac_index(system: System, subgroup: str, setting: str) -> int | None:
    # /qh, not /query: Modern Standby laptops hide LIDACTION from /query.
    result = system.run(["powercfg", "/qh", "SCHEME_CURRENT", subgroup, setting])
    if result.returncode != 0:
        return None
    match = _AC_INDEX.search(result.stdout)
    return int(match.group(1), 16) if match else None


def power_settings(system: System) -> PowerSettings:
    return PowerSettings(
        standby_ac=_ac_index(system, "SUB_SLEEP", "STANDBYIDLE"),
        hibernate_ac=_ac_index(system, "SUB_SLEEP", "HIBERNATEIDLE"),
        lid_ac=_ac_index(system, "SUB_BUTTONS", "LIDACTION"),
    )


def ollama_root(ollama_base_url: str) -> str:
    """``http://127.0.0.1:11434/v1`` -> ``http://127.0.0.1:11434`` (the native API root)."""
    root = ollama_base_url.rstrip("/")
    return root[: -len("/v1")] if root.endswith("/v1") else root


def ollama_models(system: System, ollama_base_url: str) -> list[str] | None:
    """Names of the pulled models, or ``None`` if Ollama does not answer."""
    result = system.http_get(f"{ollama_root(ollama_base_url)}/api/tags", timeout=5)
    if result.status != 200 or not isinstance(result.body, dict):
        return None
    models = result.body.get("models")
    if not isinstance(models, list):
        return None
    return [str(m["name"]) for m in models if isinstance(m, dict) and "name" in m]


def has_model(pulled: Sequence[str], wanted: str) -> bool:
    """Ollama lists an untagged pull as ``name:latest``."""
    full = wanted if ":" in wanted else f"{wanted}:latest"
    return wanted in pulled or full in pulled


@dataclass(frozen=True)
class ModelList:
    status: int  # HTTP status, 0 if unreachable
    ids: tuple[str, ...] = ()


def nvidia_models(system: System, base_url: str, api_key: str) -> ModelList:
    """``GET /v1/models``. The key only goes into the header; nothing here prints it."""
    result = system.http_get(
        f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}
    )
    if result.status != 200 or not isinstance(result.body, dict):
        return ModelList(result.status)
    data = result.body.get("data")
    if not isinstance(data, list):
        return ModelList(result.status)
    ids = sorted(str(m["id"]) for m in data if isinstance(m, dict) and "id" in m)
    return ModelList(result.status, tuple(ids))
