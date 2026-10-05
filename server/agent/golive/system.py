"""The parts of the machine that ``agent doctor`` and ``agent setup`` look at or change.

Everything goes through :class:`System`, so tests swap in a fake and never touch the real
registry, scheduler, network or processes. Commands run without a shell, and their output is
only parsed, never logged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

# Fallback when a command is not installed, mirroring the shell's "command not found".
NOT_FOUND = 127


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


@dataclass(frozen=True)
class HttpResult:
    status: int  # 0 when the server could not be reached
    body: Any = None  # parsed JSON, or None


class System(Protocol):
    platform: str  # ``sys.platform`` value, e.g. "win32"

    def python_version(self) -> tuple[int, int, int]: ...

    def which(self, name: str) -> str | None: ...

    def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
        """Run and capture output. A missing program gives ``NOT_FOUND``, never an exception."""
        ...

    def run_interactive(self, argv: Sequence[str]) -> int:
        """Run with the terminal attached (for sign-in flows and long pulls); returns the code."""
        ...

    def http_get(
        self, url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10
    ) -> HttpResult: ...

    def user_env(self, name: str) -> str | None:
        """The persisted per-user value (Windows: HKCU\\Environment), else the process value."""
        ...

    def set_user_env(self, name: str, value: str) -> None:
        """Persist a per-user environment variable. Never used for secrets."""
        ...


# Installers that do not reliably put their CLI on PATH (Tailscale's Windows installer often
# doesn't): known locations, searched only after PATH.
_KNOWN_LOCATIONS: dict[str, tuple[str, ...]] = {
    "tailscale": (r"%ProgramFiles%\Tailscale\tailscale.exe",),
}


def _resolve(name: str) -> str | None:
    found = shutil.which(name)
    if found is not None:
        return found
    for pattern in _KNOWN_LOCATIONS.get(name, ()):
        candidate = os.path.expandvars(pattern)
        if os.path.isfile(candidate):
            return candidate
    return None


class RealSystem:
    """The live machine. Only ``agent doctor`` and ``agent setup`` construct it."""

    platform = sys.platform

    def python_version(self) -> tuple[int, int, int]:
        info = sys.version_info
        return (info.major, info.minor, info.micro)

    def which(self, name: str) -> str | None:
        return _resolve(name)

    def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
        exe = _resolve(argv[0])
        if exe is None:
            return CommandResult(NOT_FOUND, "")
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [exe, *argv[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return CommandResult(NOT_FOUND, "")
        return CommandResult(done.returncode, done.stdout)

    def run_interactive(self, argv: Sequence[str]) -> int:
        exe = _resolve(argv[0])
        if exe is None:
            return NOT_FOUND
        try:
            return subprocess.run([exe, *argv[1:]], check=False).returncode  # noqa: S603
        except OSError:
            return NOT_FOUND

    def http_get(
        self, url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10
    ) -> HttpResult:
        try:
            response = httpx.get(url, headers=dict(headers or {}), timeout=timeout)
        except httpx.HTTPError:
            return HttpResult(0)
        try:
            body = response.json()
        except ValueError:
            body = None
        return HttpResult(response.status_code, body)

    def user_env(self, name: str) -> str | None:
        if sys.platform == "win32":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    return str(value)
            except OSError:
                return os.environ.get(name)
        return os.environ.get(name)

    def set_user_env(self, name: str, value: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("user environment variables can only be persisted on Windows")
        import ctypes
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        os.environ[name] = value  # later steps in this process see it too
        # Tell Explorer so new terminals pick the value up without a sign-out.
        hwnd_broadcast, wm_settingchange, smto_abortifhung = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast, wm_settingchange, 0, "Environment", smto_abortifhung, 5000, None
        )
