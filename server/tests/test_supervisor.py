from __future__ import annotations

import ctypes
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent.golive.supervisor import (
    CREATE_NEW_PROCESS_GROUP,
    CREATE_NO_WINDOW,
    EXIT_NO_JOB_OBJECT,
    server_command,
    supervise,
)


class FakeChild:
    pid = 4242

    def __init__(self, code: int) -> None:
        self.code = code

    def wait(self) -> int:
        return self.code


class FakePopen:
    def __init__(self, code: int = 0, error: OSError | None = None) -> None:
        self.code = code
        self.error = error
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> FakeChild:
        self.calls.append((command, kwargs))
        if self.error is not None:
            raise self.error
        return FakeChild(self.code)


def test_flags_are_the_documented_windows_values() -> None:
    assert CREATE_NO_WINDOW == 0x08000000
    assert CREATE_NEW_PROCESS_GROUP == 0x00000200


def test_starts_the_server_hidden_and_logs_pids_only(tmp_path: Path) -> None:
    popen, log = FakePopen(0), tmp_path / "data" / "agent.log"
    held: list[object] = []

    def job() -> object:
        held.append(object())
        return held[-1]

    code = supervise(["python.exe", "-m", "agent", "serve"], tmp_path, log, popen=popen, job=job)
    assert code == 0 and len(held) == 1
    ((command, kwargs),) = popen.calls
    assert command == ["python.exe", "-m", "agent", "serve"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    flags = kwargs["creationflags"]
    assert flags & 0x08000000 and flags & 0x00000200
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "supervisor started pid=" in lines[0]
    assert lines[1].endswith("server started pid=4242")
    assert lines[2].endswith("server exited code=0x00000000")


@pytest.mark.parametrize(
    ("code", "text"), [(3, "0x00000003"), (3221225786, "0xC000013A"), (-1073741510, "0xC000013A")]
)
def test_exit_code_is_propagated_and_logged_in_hex(tmp_path: Path, code: int, text: str) -> None:
    log = tmp_path / "agent.log"
    popen = FakePopen(code)
    assert supervise(["x"], tmp_path, log, popen=popen, job=object, max_restarts=0) == code
    assert f"server exited code={text}" in log.read_text(encoding="utf-8")
    assert len(popen.calls) == 1


def test_no_job_object_means_no_server(tmp_path: Path) -> None:
    popen, log = FakePopen(), tmp_path / "agent.log"

    def no_job() -> object:
        raise OSError(5, "denied")

    assert supervise(["x"], tmp_path, log, popen=popen, job=no_job) == EXIT_NO_JOB_OBJECT
    assert popen.calls == []
    assert "no job object" in log.read_text(encoding="utf-8")


def test_a_server_that_cannot_start_is_logged(tmp_path: Path) -> None:
    log = tmp_path / "agent.log"
    popen = FakePopen(error=FileNotFoundError(2, "missing"))
    assert supervise(["x"], tmp_path, log, popen=popen, job=object) == EXIT_NO_JOB_OBJECT
    assert "server could not start" in log.read_text(encoding="utf-8")


def test_unwritable_log_never_stops_the_server(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    log = blocker / "agent.log"  # the parent is a file, so nothing can be written
    assert supervise(["x"], tmp_path, log, popen=FakePopen(7), job=object, max_restarts=0) == 7


def test_server_command_uses_python_next_to_pythonw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    (tmp_path / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert server_command() == [str(tmp_path / "python.exe"), "-m", "agent", "serve"]
    (tmp_path / "python.exe").unlink()
    assert server_command()[0] == str(tmp_path / "pythonw.exe")


def test_server_command_prefers_the_server_virtualenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    (base / "pythonw.exe").write_text("", encoding="utf-8")
    (base / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(base / "pythonw.exe"))
    server = tmp_path / "server"
    scripts = server / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")
    assert server_command(server) == [str(scripts / "python.exe"), "-m", "agent", "serve"]
    (scripts / "python.exe").unlink()
    assert server_command(server)[0] == str(base / "python.exe")


SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102


def _wait_for_exit(pid: int, seconds: float) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
    if not handle:
        return True  # already gone
    try:
        return bool(kernel32.WaitForSingleObject(handle, int(seconds * 1000)) != WAIT_TIMEOUT)
    finally:
        kernel32.CloseHandle(handle)


def _poll(read: Callable[[], int | None], seconds: float) -> int | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read()
        if value is not None:
            return value
        time.sleep(0.2)
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="job objects exist only on Windows")
def test_killing_the_supervisor_kills_the_server(tmp_path: Path) -> None:
    log = tmp_path / "agent.log"
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from agent.golive.supervisor import supervise

        raise SystemExit(
            supervise(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                Path.cwd(),
                Path({str(log)!r}),
            )
        )
        """
    )
    supervisor = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script], cwd=Path(__file__).parents[1]
    )
    child_pid: int | None = None

    def read_pid() -> int | None:
        if not log.exists():
            return None
        for line in log.read_text(encoding="utf-8").splitlines():
            if "server started pid=" in line:
                return int(line.rsplit("=", 1)[1])
        return None

    try:
        child_pid = _poll(read_pid, 30)
        assert child_pid is not None, "the supervisor never started the server"
        assert not _wait_for_exit(child_pid, 0.5)
        supervisor.kill()  # TerminateProcess, like Stop-ScheduledTask
        supervisor.wait(timeout=10)
        assert _wait_for_exit(child_pid, 10), "the server outlived its supervisor"
    finally:
        supervisor.kill()
        if child_pid is not None:
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(child_pid), "/T", "/F"],  # noqa: S607
                capture_output=True,
                check=False,
            )


class SequencePopen(FakePopen):
    """Each start returns the next exit code from ``codes``."""

    def __init__(self, codes: list[int]) -> None:
        super().__init__()
        self.codes = list(codes)

    def __call__(self, command: list[str], **kwargs: Any) -> FakeChild:
        self.calls.append((command, kwargs))
        return FakeChild(self.codes.pop(0))


def test_a_crashed_server_is_restarted_after_a_back_off(tmp_path: Path) -> None:
    log, slept = tmp_path / "agent.log", []
    popen = SequencePopen([0xC0000005, 0])
    code = supervise(["x"], tmp_path, log, popen=popen, job=object, sleep=slept.append)
    assert code == 0 and len(popen.calls) == 2 and slept == [5.0]
    text = log.read_text(encoding="utf-8")
    assert "restarting server in 5s (crash 1)" in text


def test_supervisor_gives_up_after_too_many_crashes(tmp_path: Path) -> None:
    log, slept = tmp_path / "agent.log", []
    popen = SequencePopen([7] * 10)
    code = supervise(
        ["x"], tmp_path, log, popen=popen, job=object, max_restarts=3, sleep=slept.append
    )
    assert code == 7 and len(popen.calls) == 4 and len(slept) == 3
    assert "giving up after 4 crashes" in log.read_text(encoding="utf-8")


def test_crashes_outside_the_window_do_not_count(tmp_path: Path) -> None:
    log, now = tmp_path / "agent.log", [0.0]

    def sleep(seconds: float) -> None:
        now[0] += 1000.0  # every crash is far apart

    popen = SequencePopen([7, 7, 7, 0])
    code = supervise(
        ["x"],
        tmp_path,
        log,
        popen=popen,
        job=object,
        max_restarts=1,
        sleep=sleep,
        clock=lambda: now[0],
    )
    assert code == 0 and len(popen.calls) == 4


def test_supervisor_detaches_from_its_console_before_starting(tmp_path: Path) -> None:
    order: list[str] = []
    popen = FakePopen(0)

    def tracking_popen(command: list[str], **kwargs: Any) -> FakeChild:
        order.append("popen")
        return popen(command, **kwargs)

    supervise(
        ["x"],
        tmp_path,
        tmp_path / "agent.log",
        popen=tracking_popen,
        job=object,
        detach=lambda: order.append("detach"),
    )
    assert order == ["detach", "popen"]
