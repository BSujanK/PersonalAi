"""Console-less supervisor for the scheduled task (Windows): ``pythonw.exe -m agent supervise``.

Why: a server started from a console host dies with ``0xC000013A`` (STATUS_CONTROL_C_EXIT) when
that console gets a close or Ctrl+C event, which Windows 11 does at logon with Windows Terminal as
the default terminal. ``pythonw.exe`` is a GUI-subsystem program, so this process has no console.
It starts the server with its own hidden console (``CREATE_NO_WINDOW``) in a new process group, so
no terminal can close it or send it Ctrl+C.

It also puts itself in a job object that kills every member when its handle closes (which is when
this process ends, however it ends), so stopping the scheduled task stops the server too.

It waits for the server and exits with its exit code, so Task Scheduler's restart-on-failure and
"Last Result" reflect the server. It has no restart loop of its own. It logs pids and exit codes
to ``agent.log`` only, opening the file per line so it never holds the server's rotating log open.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
EXIT_NO_JOB_OBJECT = 1


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in "abcdef"]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_kill_on_close_job() -> object:
    """Put this process in a kill-on-close job; return the handle, which the caller must keep.

    Children inherit the membership. Raises ``OSError`` (with the Windows error) on failure.
    """
    if sys.platform != "win32":
        raise OSError("job objects exist only on Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        handle,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if ok and kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        return handle
    error = ctypes.get_last_error()
    kernel32.CloseHandle(handle)
    raise ctypes.WinError(error)


def server_command() -> list[str]:
    """``python.exe -m agent serve``, from the ``python.exe`` next to this ``pythonw.exe``."""
    exe = Path(sys.executable)
    sibling = exe.with_name("python.exe")
    python = sibling if sibling.is_file() else exe
    return [str(python), "-m", "agent", "serve"]


def _log(log_path: Path, message: str) -> None:
    """Append one line and close the file again; the server's own handler owns the file."""
    stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with contextlib.suppress(OSError), log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} INFO agent.supervisor {message}\n")


def supervise(
    command: Sequence[str],
    cwd: Path,
    log_path: Path,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    job: Callable[[], object] = create_kill_on_close_job,
) -> int:
    """Run ``command`` hidden under a kill-on-close job and return its exit code."""
    with contextlib.suppress(OSError):
        log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        held = job()  # keep the handle: closing it (process end) kills the members
    except OSError as exc:
        _log(
            log_path, f"no job object: errno={exc.errno} winerror={getattr(exc, 'winerror', None)}"
        )
        return EXIT_NO_JOB_OBJECT
    _log(log_path, f"supervisor started pid={os.getpid()}")
    try:
        child = popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as exc:
        _log(log_path, f"server could not start: errno={exc.errno}")
        return EXIT_NO_JOB_OBJECT
    _log(log_path, f"server started pid={child.pid}")
    code: int = child.wait()
    _log(log_path, f"server exited code=0x{code & 0xFFFFFFFF:08X}")
    del held  # released only now, after the server is gone
    return code
