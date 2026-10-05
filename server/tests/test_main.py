from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn

import agent.main as main_module
from agent.main import main
from agent.scheduler import (
    DEADLINE_JOB_ID,
    FILE_INDEX_JOB_ID,
    FINANCE_CATEGORIZE_JOB_ID,
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


def test_pair_prints_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    assert main(["pair"]) == 0
    out = capsys.readouterr().out
    assert "Pairing code: " in out
    assert "http://127.0.0.1:8765/pair" in out


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
        (FINANCE_CATEGORIZE_JOB_ID, 15),
    ]
    assert scheduler.shutdowns == [False]


def test_serve_without_accounts_only_categorises_finance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = _serve_env(monkeypatch, tmp_path)
    captured, _ = _capture_jobs(monkeypatch)
    assert main(["serve"]) == 0
    assert started == ["127.0.0.1"]
    assert [(job.id, job.minutes) for job in captured[0]] == [(FINANCE_CATEGORIZE_JOB_ID, 15)]


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
        (DEADLINE_JOB_ID, 60),
        (FILE_INDEX_JOB_ID, 30),
        (FINANCE_CATEGORIZE_JOB_ID, 15),
    ]


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
