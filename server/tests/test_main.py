from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import uvicorn

import agent.main as main_module
from agent.connectors.google_auth import GoogleNotConfigured
from agent.core.clock import utcnow
from agent.mail.sync import SyncStats
from agent.main import main
from agent.scheduler import (
    DEADLINE_JOB_ID,
    FILE_INDEX_JOB_ID,
    FINANCE_CATEGORIZE_JOB_ID,
    MAIL_JOB_ID,
    Job,
)
from agent.store.db import Database
from agent.store.sync_status import (
    CLASSROOM,
    last_failure,
    last_ok,
    mail_status_name,
    record_failure,
)
from agent.workspace.deadlines import DeadlineScanResult


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


def _scan(result: DeadlineScanResult) -> Callable[[], DeadlineScanResult]:
    return lambda: result


def test_deadline_scan_where_every_account_fails_is_not_ok() -> None:
    db = Database(":memory:")
    failures = {"a@example.edu": "GoogleNotConfigured", "b@example.edu": "GoogleNotConfigured"}
    main_module._run_deadline_scan(db, _scan(DeadlineScanResult(0, 0, failures)))
    assert last_ok(db, CLASSROOM) is None
    failure = last_failure(db, CLASSROOM)
    assert failure is not None
    assert failure[1] == "GoogleNotConfigured for 2 of 2 accounts"


def test_deadline_scan_reason_lists_distinct_types_sorted() -> None:
    db = Database(":memory:")
    failures = {"a@example.edu": "ValueError", "b@example.edu": "GoogleNotConfigured"}
    main_module._run_deadline_scan(db, _scan(DeadlineScanResult(0, 0, failures)))
    failure = last_failure(db, CLASSROOM)
    assert failure is not None
    assert failure[1] == "GoogleNotConfigured, ValueError for 2 of 2 accounts"


def test_deadline_scan_with_one_account_ok_records_ok_and_clears_failure() -> None:
    db = Database(":memory:")
    record_failure(db, CLASSROOM, "ValueError", utcnow)
    main_module._run_deadline_scan(db, _scan(DeadlineScanResult(0, 1, {"b@example.edu": "X"})))
    assert last_ok(db, CLASSROOM) is not None
    assert last_failure(db, CLASSROOM) is None


def test_deadline_scan_that_did_nothing_records_nothing() -> None:
    db = Database(":memory:")
    main_module._run_deadline_scan(db, _scan(DeadlineScanResult(0, 0, {})))
    assert last_ok(db, CLASSROOM) is None
    assert last_failure(db, CLASSROOM) is None


def test_deadline_scan_that_raises_records_the_type_and_reraises() -> None:
    db = Database(":memory:")

    def boom() -> DeadlineScanResult:
        raise GoogleNotConfigured("private detail")

    with pytest.raises(GoogleNotConfigured):
        main_module._run_deadline_scan(db, boom)
    failure = last_failure(db, CLASSROOM)
    assert failure is not None
    assert failure[1] == "GoogleNotConfigured"
    assert "private" not in failure[1]


class _FakeSync:
    def __init__(self, results: dict[str, SyncStats | str]) -> None:
        self._results = results

    def sync_all(self, accounts: object) -> dict[str, SyncStats | str]:
        return self._results


def test_mail_sync_records_each_account_separately() -> None:
    db = Database(":memory:")
    good, bad = "me@example.com", "second@example.org"
    sync = _FakeSync({good: SyncStats(added=1), bad: "GoogleNotConfigured"})
    main_module._run_mail_sync(db, sync, [good, bad])  # type: ignore[arg-type]
    assert last_ok(db, mail_status_name(good)) is not None
    assert last_failure(db, mail_status_name(good)) is None
    assert last_ok(db, mail_status_name(bad)) is None
    failure = last_failure(db, mail_status_name(bad))
    assert failure is not None
    assert failure[1] == "GoogleNotConfigured"


def _no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdout", None)
    monkeypatch.setattr("sys.stderr", None)


def test_serve_without_console_logs_to_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys

    from agent.config import Settings

    settings = Settings(db_path=tmp_path / "data" / "agent.db")
    _no_console(monkeypatch)
    main_module._redirect_console_to_log(settings)
    stream = sys.stderr
    assert stream is not None and sys.stdout is stream
    print("first line")
    print("second line", file=sys.stderr)
    stream.close()
    log = tmp_path / "data" / "agent.log"
    assert log.read_text(encoding="utf-8") == "first line\nsecond line\n"
    assert not log.with_name("agent.log.1").exists()


def test_log_is_rotated_when_over_5_mb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import sys

    from agent.config import Settings

    log = tmp_path / "agent.log"
    log.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    older = tmp_path / "agent.log.1"
    older.write_text("older", encoding="utf-8")
    _no_console(monkeypatch)
    main_module._redirect_console_to_log(Settings(db_path=tmp_path / "agent.db"))
    stream = sys.stderr
    assert stream is not None
    print("fresh")
    stream.close()
    assert log.read_text(encoding="utf-8") == "fresh\n"
    assert older.stat().st_size == 5 * 1024 * 1024 + 1


def test_console_is_left_alone_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agent.config import Settings

    main_module._redirect_console_to_log(Settings(db_path=tmp_path / "agent.db"))
    assert not (tmp_path / "agent.log").exists()
