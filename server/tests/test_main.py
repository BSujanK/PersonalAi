from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn

import agent.main as main_module
from agent.main import main


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


def test_serve_with_mail_accounts_polls_and_stops_scheduler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = _serve_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PERSONALAI_MAIL_ACCOUNTS", "me@example.com,second@example.org")
    scheduler = _FakeScheduler()
    polled: list[tuple[tuple[str, ...], int]] = []

    def fake_start(sync: object, accounts: tuple[str, ...], minutes: int) -> _FakeScheduler:
        polled.append((tuple(accounts), minutes))
        return scheduler

    monkeypatch.setattr(main_module, "start_mail_polling", fake_start)
    assert main(["serve"]) == 0
    assert started == ["127.0.0.1"]
    assert polled == [(("me@example.com", "second@example.org"), 5)]
    assert scheduler.shutdowns == [False]


def test_serve_without_mail_accounts_disables_mail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = _serve_env(monkeypatch, tmp_path)

    def must_not_start(*_a: object) -> None:
        raise AssertionError("mail polling must be off")

    monkeypatch.setattr(main_module, "start_mail_polling", must_not_start)
    assert main(["serve"]) == 0
    assert started == ["127.0.0.1"]


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
