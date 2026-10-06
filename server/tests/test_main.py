from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
import uvicorn

import agent.main as main_module
from agent.main import main
from agent.scheduler import (
    ALERT_JOB_ID,
    CLASSROOM_DEADLINE_JOB_ID,
    FILE_INDEX_JOB_ID,
    FINANCE_CATEGORIZE_JOB_ID,
    MAIL_DEADLINE_JOB_ID,
    MAIL_JOB_ID,
    Job,
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))

    def must_not_run(self: uvicorn.Server) -> None:
        raise AssertionError("uvicorn must not start")

    monkeypatch.setattr(uvicorn.Server, "run", must_not_run)
    return monkeypatch


def test_serve_refuses_public_bind(env: pytest.MonkeyPatch) -> None:
    env.setattr(main_module, "assert_secure_backend", lambda: None)
    env.setenv("PERSONALAI_BIND_HOSTS", "0.0.0.0")  # noqa: S104
    assert main(["serve"]) == 2


def test_serve_refuses_lan_bind_among_others(env: pytest.MonkeyPatch) -> None:
    env.setattr(main_module, "assert_secure_backend", lambda: None)
    env.setenv("PERSONALAI_BIND_HOSTS", "127.0.0.1,192.168.1.10")
    assert main([]) == 2


def test_serve_refuses_insecure_keyring(env: pytest.MonkeyPatch) -> None:
    # The autouse in-memory keyring is deliberately not on the allowlist.
    env.setenv("PERSONALAI_BIND_HOSTS", "127.0.0.1")
    assert main(["serve"]) == 2


def test_serve_refuses_bad_port(env: pytest.MonkeyPatch) -> None:
    env.setenv("PERSONALAI_PORT", "abc")
    assert main(["serve"]) == 2


def test_serve_starts_uvicorn_when_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started: list[str] = []
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("PERSONALAI_BIND_HOSTS", "127.0.0.1")
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: started.append(self.config.host))
    assert main(["serve"]) == 0
    assert started == ["127.0.0.1"]


def test_pair_without_tailscale_bind_prints_code_and_explains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    monkeypatch.setattr(main_module.segno, "make", _no_qr)
    assert main(["pair"]) == 0
    out = capsys.readouterr().out
    assert "Pairing code: " in out
    assert "No Tailscale bind address" in out


def _no_qr(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("no QR without a reachable address")


@pytest.mark.parametrize(
    ("hosts", "argv", "url"),
    [
        ("127.0.0.1,100.101.102.103", ["pair"], "http://100.101.102.103:8765"),
        ("fd7a:115c:a1e0::5", ["pair"], "http://[fd7a:115c:a1e0::5]:8765"),
        ("127.0.0.1", ["pair", "--url", "http://laptop.tail1.ts.net:8765/"], None),
    ],
)
def test_pair_prints_qr_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    hosts: str,
    argv: list[str],
    url: str | None,
) -> None:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("PERSONALAI_BIND_HOSTS", hosts)
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    payloads: list[str] = []
    real_make = main_module.segno.make

    def capture(content: str, **kwargs: object) -> object:
        payloads.append(content)
        return real_make(content, **kwargs)

    monkeypatch.setattr(main_module.segno, "make", capture)
    assert main(argv) == 0
    out = capsys.readouterr().out
    [payload] = payloads
    data = json.loads(payload)
    code = out.split("Pairing code: ")[1].split()[0]
    assert data == {"v": 1, "url": url or "http://laptop.tail1.ts.net:8765", "code": code}


class _FakeScheduler:
    def __init__(self) -> None:
        self.shutdowns: list[bool] = []

    def shutdown(self, wait: bool = True) -> None:
        self.shutdowns.append(wait)


def _serve_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    started: list[str] = []
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("PERSONALAI_BIND_HOSTS", "127.0.0.1")
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: started.append(self.config.host))
    return started


def _capture_jobs(monkeypatch: pytest.MonkeyPatch) -> tuple[list[list[Job]], _FakeScheduler]:
    captured: list[list[Job]] = []
    scheduler = _FakeScheduler()

    def fake_start(jobs: list[Job]) -> _FakeScheduler | None:
        captured.append(list(jobs))
        return scheduler if jobs else None

    monkeypatch.setattr(main_module, "start_jobs", fake_start)
    return captured, scheduler


def test_serve_with_mail_accounts_polls_and_stops_scheduler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_MAIL_ACCOUNTS", "me@example.com,second@example.org")
    captured, scheduler = _capture_jobs(monkeypatch)
    assert main(["serve"]) == 0
    assert started == ["127.0.0.1"]
    assert [(job.id, job.minutes) for job in captured[0]] == [
        (MAIL_JOB_ID, 5),
        (MAIL_DEADLINE_JOB_ID, 24 * 60),
        (FINANCE_CATEGORIZE_JOB_ID, 15),
        (ALERT_JOB_ID, 5),
    ]
    assert scheduler.shutdowns == [False]
    [scan] = [j for j in captured[0] if j.id == MAIL_DEADLINE_JOB_ID]
    assert 0 < scan.start_delay_seconds <= 300  # a kick shortly after startup, then daily
    assert [j.start_delay_seconds for j in captured[0] if j is not scan] == [0, 0, 0]


def test_serve_without_accounts_only_categorises_finance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = _serve_env(monkeypatch, tmp_path)
    captured, _ = _capture_jobs(monkeypatch)
    assert main(["serve"]) == 0
    assert started == ["127.0.0.1"]
    assert [(job.id, job.minutes) for job in captured[0]] == [
        (FINANCE_CATEGORIZE_JOB_ID, 15),
        (ALERT_JOB_ID, 5),
    ]


def test_serve_with_workspace_registers_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve_env(monkeypatch, tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setenv("PERSONALAI_CALENDAR_ACCOUNTS", "me@example.com")
    monkeypatch.setenv("PERSONALAI_CLASSROOM_ACCOUNTS", "student@example.edu")
    monkeypatch.setenv("PERSONALAI_DRIVE_ACCOUNTS", "me@example.com")
    monkeypatch.setenv("PERSONALAI_FILE_ROOTS", str(docs))
    captured, _ = _capture_jobs(monkeypatch)
    assert main(["serve"]) == 0
    assert [(job.id, job.minutes) for job in captured[0]] == [
        (CLASSROOM_DEADLINE_JOB_ID, 60),
        (FILE_INDEX_JOB_ID, 30),
        (FINANCE_CATEGORIZE_JOB_ID, 15),
        (ALERT_JOB_ID, 5),
    ]


def test_classroom_job_without_google_tokens_is_recorded_as_failing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agent.store.db import Database
    from agent.store.sync_status import CLASSROOM, last_failure, last_ok

    _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_CALENDAR_ACCOUNTS", "me@example.com")
    monkeypatch.setenv("PERSONALAI_CLASSROOM_ACCOUNTS", "student@example.edu")
    captured, _ = _capture_jobs(monkeypatch)
    assert main(["serve"]) == 0
    [classroom_job] = [j for j in captured[0] if j.id == CLASSROOM_DEADLINE_JOB_ID]
    classroom_job.run()  # no OAuth client or token in the (in-memory) keyring
    db = Database(tmp_path / "agent.db")
    assert last_ok(db, CLASSROOM) is None
    failure = last_failure(db, CLASSROOM)
    assert failure is not None
    assert failure.reason == "1 of 1 account(s) failed: GoogleNotConfigured"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PERSONALAI_FILE_ROOTS", "relative/folder"),
        ("PERSONALAI_DEADLINE_CALENDAR", "other@example.com"),
    ],
)
def test_serve_refuses_bad_workspace_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str
) -> None:
    _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_CALENDAR_ACCOUNTS", "me@example.com")
    monkeypatch.setenv(name, value)
    _capture_jobs(monkeypatch)
    assert main(["serve"]) == 2


def test_serve_refuses_non_loopback_ollama_when_mail_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_MAIL_ACCOUNTS", "me@example.com")
    monkeypatch.setattr(
        main_module.Settings,
        "from_env",
        classmethod(
            lambda cls, env=None: cls(
                db_path=tmp_path / "agent.db",
                mail_accounts=("me@example.com",),
                ollama_base_url="http://192.168.1.5:11434/v1",
            )
        ),
    )
    assert main(["serve"]) == 2


def test_doctor_and_setup_subcommands_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.main as main_module

    seen: list[object] = []
    monkeypatch.setattr(
        main_module, "run_doctor", lambda *a, **kw: seen.append(("doctor", kw["as_json"])) or 0
    )
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    monkeypatch.setattr(
        main_module, "run_setup", lambda *a, **kw: seen.append(("setup", list(kw["redo"]))) or 0
    )
    assert main_module.main(["doctor", "--json"]) == 0
    assert main_module.main(["setup", "--redo", "pair", "--redo", "power"]) == 0
    assert seen == [("doctor", True), ("setup", ["pair", "power"])]


@pytest.fixture
def clean_agent_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("agent")
    before = list(logger.handlers)
    logger.handlers[:] = []
    yield logger
    for handler in logger.handlers:
        handler.close()
    logger.handlers[:] = before


def test_serve_logs_to_a_rotating_file_next_to_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_agent_logger: logging.Logger
) -> None:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "data" / "agent.db"))
    monkeypatch.setenv("PERSONALAI_BIND_HOSTS", "127.0.0.1")
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    assert main(["serve"]) == 0
    assert main(["serve"]) == 0  # no duplicate handlers the second time
    handlers = [
        h
        for h in clean_agent_logger.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename) == (tmp_path / "data" / "agent.log").absolute()
    assert (handlers[0].maxBytes, handlers[0].backupCount) == (1_000_000, 3)
    handlers[0].flush()
    text = (tmp_path / "data" / "agent.log").read_text(encoding="utf-8")
    assert text.count("server starting: hosts=1 port=8765") == 2


def test_serve_without_stderr_still_logs_to_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_agent_logger: logging.Logger
) -> None:
    monkeypatch.setattr(sys, "stderr", None)  # pythonw
    settings = main_module.Settings.from_env({"PERSONALAI_DB_PATH": str(tmp_path / "agent.db")})
    main_module._configure_logging(settings)
    assert not any(type(h) is logging.StreamHandler for h in clean_agent_logger.handlers)
    assert any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in clean_agent_logger.handlers
    )


def test_serve_logs_a_crash_by_type_only_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_agent_logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)

    def boom(self: uvicorn.Server) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(uvicorn.Server, "run", boom)
    monkeypatch.setenv("PERSONALAI_BIND_HOSTS", "127.0.0.1")
    caplog.set_level(logging.INFO, logger="agent")
    with pytest.raises(RuntimeError):
        main(["serve"])
    assert "server crashed: RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text


def test_supervise_subcommand_runs_the_server_under_the_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "data" / "agent.db"))
    monkeypatch.setattr(sys, "platform", "win32")
    seen: list[tuple[list[str], Path, Path]] = []

    def fake_supervise(command: Sequence[str], cwd: Path, log_path: Path) -> int:
        seen.append((list(command), cwd, log_path))
        return 7

    monkeypatch.setattr(main_module, "supervise", fake_supervise)
    assert main(["supervise"]) == 7
    ((command, cwd, log_path),) = seen
    assert command[1:] == ["-m", "agent", "serve"]
    assert cwd == main_module.SERVER_DIR
    assert log_path == tmp_path / "data" / "agent.log"


def test_supervise_is_windows_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        main_module, "supervise", lambda *a, **k: pytest.fail("no supervisor off Windows")
    )
    assert main(["supervise"]) == 1
    assert "only available on Windows" in capsys.readouterr().err
