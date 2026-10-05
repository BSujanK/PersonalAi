"""Read-only probes shared by ``agent doctor`` and ``agent setup``. Nothing here changes state."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass

from agent.golive.system import System

TASK_NAME = "PersonalAi agent"
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
    result = system.run(["powercfg", "/query", "SCHEME_CURRENT", subgroup, setting])
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
