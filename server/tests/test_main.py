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
