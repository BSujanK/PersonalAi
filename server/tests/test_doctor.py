from __future__ import annotations

import io
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import keyring
import pytest

from agent.config import Settings
from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    SERVICE_SCOPES,
    token_secret_name,
)
from agent.core.audit import AuditLog
from agent.golive.doctor import CheckResult, run_checks, run_doctor
from agent.golive.probes import POWER_FIX_COMMANDS
from agent.golive.system import NOT_FOUND, CommandResult, HttpResult
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from agent.store.sync_status import (
    CLASSROOM,
    SMS_INGEST,
    mail_status_name,
    record_failure,
    record_ok,
)
from tests.conftest import InMemoryKeyring
from tests.support import START, FakeClock

NVIDIA_KEY = "nvapi-FAKEKEYVALUE0123456789"
ACCESS_TOKEN = "ya29.FAKE-ACCESS-TOKEN-VALUE"
REFRESH_TOKEN = "1//FAKE-REFRESH-TOKEN-VALUE"
ACCOUNT = "me@example.com"
TS_IP = "100.101.102.103"

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/models"
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
SCHTASKS = ("schtasks", "/Query", "/TN", "PersonalAi agent", "/FO", "LIST")
TAILSCALE = ("tailscale", "ip", "-4")
POWERCFG = {
    "STANDBYIDLE": ("SUB_SLEEP", "STANDBYIDLE"),
    "HIBERNATEIDLE": ("SUB_SLEEP", "HIBERNATEIDLE"),
    "LIDACTION": ("SUB_BUTTONS", "LIDACTION"),
}

SCHTASKS_RUNNING = (
    "Folder: \\\nHostName:      LAPTOP-EXAMPLE\nTaskName:      \\PersonalAi agent\n"
    "Next Run Time: N/A\nStatus:        Running\nLogon Mode:    Interactive only\n"
)
SCHTASKS_READY = SCHTASKS_RUNNING.replace("Running", "Ready")
SCHTASKS_LOCALISED = SCHTASKS_RUNNING.replace("Status:        Running\n", "")


def powercfg_output(value: int) -> str:
    return (
        "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)\n"
        "  GUID Alias: STANDBYIDLE\n"
        "    Possible Setting Index: 0x00000000\n"
        f"    Current AC Power Setting Index: 0x{value:08x}\n"
        "    Current DC Power Setting Index: 0x00000384\n"
    )


@dataclass
class FakeSystem:
    platform: str = "win32"
    python: tuple[int, int, int] = (3, 12, 4)
    programs: set[str] = field(default_factory=lambda: {"uv"})
    commands: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    urls: dict[str, HttpResult] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    explode_on_http: bool = False

    def python_version(self) -> tuple[int, int, int]:
        return self.python

    def which(self, name: str) -> str | None:
        return f"C:\\bin\\{name}.exe" if name in self.programs else None

    def run(self, argv: Sequence[str], *, timeout: float = 30) -> CommandResult:
        return self.commands.get(tuple(argv), CommandResult(NOT_FOUND, ""))

    def run_interactive(self, argv: Sequence[str]) -> int:
        raise AssertionError("doctor must not run interactive commands")

    def http_get(
        self, url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10
    ) -> HttpResult:
        if self.explode_on_http:
            raise RuntimeError(f"boom with {headers}")
        return self.urls.get(url, HttpResult(0))

    def user_env(self, name: str) -> str | None:
        return self.env.get(name)

    def set_user_env(self, name: str, value: str) -> None:
        raise AssertionError("doctor must not change the environment")


@dataclass
class Env:
    settings: Settings
    system: FakeSystem
    keystore: KeyStore
    clock: FakeClock
    db_key: bytes

    def results(self) -> dict[str, CheckResult]:
        return {
            r.id: r for r in run_checks(self.settings, self.system, self.keystore, clock=self.clock)
        }

    def result(self, check_id: str) -> CheckResult:
        return self.results()[check_id]

    def doctor(self, *, as_json: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        code = run_doctor(
            self.settings, self.system, self.keystore, as_json=as_json, out=out, clock=self.clock
        )
        return code, out.getvalue()


def _token(scopes: list[str], refresh: str | None = REFRESH_TOKEN) -> str:
    data: dict[str, Any] = {"token": ACCESS_TOKEN, "scopes": scopes}
    if refresh:
        data["refresh_token"] = refresh
    return json.dumps(data)


def _all_scopes(*services: str) -> list[str]:
    return [s for name in services for s in SERVICE_SCOPES[name]]


def _win_vault_backend() -> InMemoryKeyring:
    cls = type("WinVaultKeyring", (InMemoryKeyring,), {"__module__": "keyring.backends.Windows"})
    return cls()  # type: ignore[no-any-return]


def _build_db(path: Path, db_key: bytes, clock: FakeClock) -> None:
    db = Database(path)
    cipher = FieldCipher(db_key)
    db.execute("INSERT INTO conversations (id, created_at) VALUES ('c1', 't')")
    message_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO messages (id, conversation_id, seq, created_at, role, content_enc) "
        "VALUES (?, 'c1', 1, 't', 'user', ?)",
        (message_id, cipher.encrypt("hello", f"messages.content:{message_id}")),
    )
    db.execute(
        "INSERT INTO devices (id, name, token_hash, created_at) "
        "VALUES ('d1', 'Test phone', 'hash', 't')"
    )
    AuditLog(db, clock).record("test_event", actor="test")
    db.execute(
        "INSERT INTO mail_accounts (account, history_id, last_sync_at) VALUES (?, '1', ?)",
        (ACCOUNT, (clock() - timedelta(minutes=4)).isoformat()),
    )
    record_ok(db, SMS_INGEST, lambda: clock() - timedelta(hours=2))
    record_ok(db, CLASSROOM, lambda: clock() - timedelta(minutes=30))
    db.close()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    keyring.set_keyring(_win_vault_backend())  # the autouse fixture restores the previous one
    keystore = KeyStore()
    clock = FakeClock()
    db_key = bytes(range(32))
    keystore.set_bytes("db_key", db_key)
    keystore.set("nvidia_api_key", NVIDIA_KEY)
    keystore.set(CLIENT_SECRET_NAME, json.dumps({"installed": {"client_id": "id"}}))
    keystore.set(token_secret_name(ACCOUNT), _token(_all_scopes("gmail", "classroom", "calendar")))
    path = tmp_path / "agent.db"
    _build_db(path, db_key, clock)
    settings = Settings(
        bind_hosts=("127.0.0.1", TS_IP),
        db_path=path,
        model_primary="vendor/primary-model",
        model_fallback="vendor/fallback-model",
        model_long="vendor/long-model",
        mail_accounts=(ACCOUNT,),
        calendar_accounts=(ACCOUNT,),
        classroom_accounts=(ACCOUNT,),
    )
    system = FakeSystem(
        env={"OLLAMA_CONTEXT_LENGTH": "8192"},
        commands={
            TAILSCALE: CommandResult(0, f"{TS_IP}\n"),
            SCHTASKS: CommandResult(0, SCHTASKS_RUNNING),
            **{
                ("powercfg", "/qh", "SCHEME_CURRENT", *args): CommandResult(0, powercfg_output(0))
                for args in POWERCFG.values()
            },
        },
        urls={
            NVIDIA_URL: HttpResult(
                200,
                {
                    "data": [
                        {"id": "vendor/primary-model"},
                        {"id": "vendor/fallback-model"},
                        {"id": "vendor/long-model"},
                    ]
                },
            ),
            OLLAMA_URL: HttpResult(200, {"models": [{"name": "qwen2.5:3b"}]}),
        },
    )
    return Env(settings, system, keystore, clock, db_key)


def test_healthy_machine_passes_everything(env: Env) -> None:
    results = env.results()
    assert [r.id for r in results.values()] == [
        "python",
        "uv",
        "keyring",
        "nvidia_key",
        "nvidia_models",
        "ollama",
        "ollama_context",
        f"google:{ACCOUNT}",
        "bind_hosts",
        "tailscale",
        "database",
        "audit_chain",
        "scheduled_task",
        "power",
        "paired_device",
        "last_mail_sync",
        "last_sms_ingest",
        "last_classroom_sync",
    ]
    assert {r.id: r.status for r in results.values() if r.status != "pass"} == {}
    code, text = env.doctor()
    assert code == 0
    assert text.splitlines()[0] == "PersonalAi doctor"
    assert "[PASS] Python 3.12.4" in text
    assert "15/15 required checks passed.\n" in text


# --- python, uv, keyring ---------------------------------------------------------------------


def test_python(env: Env) -> None:
    env.system.python = (3, 11, 9)
    result = env.result("python")
    assert (result.status, result.title) == ("fail", "Python 3.11.9")
    assert "python.org" in result.fix


def test_uv(env: Env) -> None:
    env.system.programs = set()
    result = env.result("uv")
    assert result.status == "fail"
    assert result.fix == "winget install --id=astral-sh.uv -e"


def test_keyring_in_memory_backend_is_insecure(env: Env) -> None:
    keyring.set_keyring(InMemoryKeyring())
    result = env.result("keyring")
    assert result.status == "fail"
    assert "InMemoryKeyring" in result.detail
    assert "SETUP" in result.fix


def test_keyring_secure_but_not_windows_vault_on_windows(env: Env) -> None:
    cls = type("Keyring", (InMemoryKeyring,), {"__module__": "keyring.backends.SecretService"})
    keyring.set_keyring(cls())
    assert env.result("keyring").status == "fail"


def test_keyring_chainer_with_vault_member(env: Env) -> None:
    class Chain(InMemoryKeyring):
        backends = (_win_vault_backend(),)

    chain = type("ChainerBackend", (Chain,), {"__module__": "keyring.backends.chainer"})()
    keyring.set_keyring(chain)
    result = env.result("keyring")
    assert (result.status, result.detail) == ("pass", "ChainerBackend")


def test_keyring_on_linux_skips_vault_part(env: Env) -> None:
    cls = type("Keyring", (InMemoryKeyring,), {"__module__": "keyring.backends.SecretService"})
    keyring.set_keyring(cls())
    env.system.platform = "linux"
    assert env.result("keyring").status == "pass"
    keyring.set_keyring(InMemoryKeyring())
    assert env.result("keyring").status == "fail"


# --- NVIDIA ----------------------------------------------------------------------------------


def test_nvidia_key(env: Env) -> None:
    env.keystore.delete("nvidia_api_key")
    result = env.result("nvidia_key")
    assert (result.status, result.title) == ("fail", "NVIDIA key in keyring")
    assert "python -m agent setup" in result.fix
    assert "keyring set PersonalAi nvidia_api_key" in result.fix


def test_nvidia_models_skipped_without_key(env: Env) -> None:
    env.keystore.delete("nvidia_api_key")
    assert env.result("nvidia_models").status == "skip"


@pytest.mark.parametrize(
    ("http", "needle"),
    [
        (HttpResult(0), "unreachable"),
        (HttpResult(401), "rejected"),
        (HttpResult(403), "rejected"),
        (HttpResult(502), "HTTP 502"),
    ],
)
def test_nvidia_models_http_failures(env: Env, http: HttpResult, needle: str) -> None:
    env.system.urls[NVIDIA_URL] = http
    result = env.result("nvidia_models")
    assert result.status == "fail"
    assert needle in result.detail


def test_nvidia_models_primary_unset(env: Env) -> None:
    env.settings = replace(env.settings, model_primary="")
    result = env.result("nvidia_models")
    assert result.status == "fail"
    assert "PERSONALAI_MODEL_PRIMARY is not set" in result.detail
    assert "eval_models.py --list-models" in result.fix
    assert '"PERSONALAI_MODEL_PRIMARY"' in result.fix


def test_nvidia_models_listed_model_missing(env: Env) -> None:
    env.settings = replace(env.settings, model_long="vendor/retired-model")
    result = env.result("nvidia_models")
    assert result.status == "fail"
    assert "PERSONALAI_MODEL_LONG=vendor/retired-model" in result.detail
    assert NVIDIA_KEY not in result.detail + result.fix


def test_nvidia_models_optional_models_may_be_unset(env: Env) -> None:
    env.settings = replace(env.settings, model_fallback="", model_long="")
    assert env.result("nvidia_models").status == "pass"


# --- Ollama ----------------------------------------------------------------------------------


def test_ollama_unreachable(env: Env) -> None:
    env.system.urls[OLLAMA_URL] = HttpResult(0)
    result = env.result("ollama")
    assert result.status == "fail"
    assert "start Ollama" in result.fix


def test_ollama_model_not_pulled(env: Env) -> None:
    env.settings = replace(env.settings, ollama_model="llama3.2:3b")
    result = env.result("ollama")
    assert result.status == "fail"
    assert result.fix == "ollama pull llama3.2:3b"


def test_ollama_untagged_pull_counts(env: Env) -> None:
    env.settings = replace(env.settings, classifier_model="tiny", ollama_model="tiny")
    env.system.urls[OLLAMA_URL] = HttpResult(200, {"models": [{"name": "tiny:latest"}]})
    assert env.result("ollama").status == "pass"


def test_ollama_non_loopback_url_fails(env: Env) -> None:
    env.settings = replace(env.settings, ollama_base_url="http://192.0.2.5:11434/v1")
    result = env.result("ollama")
    assert result.status == "fail"
    assert "loopback" in result.detail


@pytest.mark.parametrize("value", [None, "", "abc", "4096"])
def test_ollama_context_fails(env: Env, value: str | None) -> None:
    env.system.env.pop("OLLAMA_CONTEXT_LENGTH")
    if value is not None:
        env.system.env["OLLAMA_CONTEXT_LENGTH"] = value
    result = env.result("ollama_context")
    assert result.status == "fail"
    assert '"OLLAMA_CONTEXT_LENGTH", "8192", "User"' in result.fix
    assert "restart" in result.fix or "start it again" in result.fix


def test_ollama_context_larger_value_passes(env: Env) -> None:
    env.system.env["OLLAMA_CONTEXT_LENGTH"] = "16384"
    assert env.result("ollama_context").status == "pass"


# --- Google ----------------------------------------------------------------------------------


def test_google_missing_client(env: Env) -> None:
    env.keystore.delete(CLIENT_SECRET_NAME)
    result = env.result(f"google:{ACCOUNT}")
    assert result.status == "fail"
    assert f"--account {ACCOUNT} --services gmail,calendar,classroom" in result.fix


def test_google_missing_token(env: Env) -> None:
    env.keystore.delete(token_secret_name(ACCOUNT))
    assert env.result(f"google:{ACCOUNT}").status == "fail"


def test_google_token_without_refresh_token(env: Env) -> None:
    env.keystore.set(
        token_secret_name(ACCOUNT), _token(_all_scopes("gmail", "classroom", "calendar"), None)
    )
    result = env.result(f"google:{ACCOUNT}")
    assert result.status == "fail"
    assert "refresh" in result.detail


def test_google_missing_scopes_name_services_only(env: Env) -> None:
    env.keystore.set(token_secret_name(ACCOUNT), _token(_all_scopes("gmail")))
    result = env.result(f"google:{ACCOUNT}")
    assert result.status == "fail"
    assert result.detail == "granted: gmail; missing: calendar, classroom"
    assert result.fix.endswith("--services calendar,classroom")
    assert ACCESS_TOKEN not in result.detail + result.fix


def test_google_partial_classroom_scopes_count_as_missing(env: Env) -> None:
    scopes = _all_scopes("gmail", "calendar") + list(SERVICE_SCOPES["classroom"][:1])
    env.keystore.set(token_secret_name(ACCOUNT), _token(scopes))
    assert "missing: classroom" in env.result(f"google:{ACCOUNT}").detail


def test_google_corrupt_token_is_a_generic_failure(env: Env) -> None:
    env.keystore.set(token_secret_name(ACCOUNT), "not json {")
    result = env.result(f"google:{ACCOUNT}")
    assert result.status == "fail"


def test_google_one_result_per_account_with_only_its_services(env: Env) -> None:
    env.settings = replace(env.settings, drive_accounts=("other@example.com",))
    env.keystore.set(token_secret_name("other@example.com"), _token(_all_scopes("drive")))
    results = env.results()
    assert results["google:other@example.com"].status == "pass"
    assert results[f"google:{ACCOUNT}"].status == "pass"


def test_google_no_accounts_is_a_warning(env: Env) -> None:
    env.settings = replace(
        env.settings, mail_accounts=(), calendar_accounts=(), classroom_accounts=()
    )
    result = env.result("google")
    assert (result.status, result.required) == ("warn", False)


# --- bind hosts, Tailscale -------------------------------------------------------------------


def test_bind_hosts_without_tailscale_address(env: Env) -> None:
    env.settings = replace(env.settings, bind_hosts=("127.0.0.1",))
    result = env.result("bind_hosts")
    assert result.status == "fail"
    assert f'"PERSONALAI_BIND_HOSTS", "127.0.0.1,{TS_IP}", "User"' in result.fix


def test_bind_hosts_fix_without_detected_tailscale(env: Env) -> None:
    env.settings = replace(env.settings, bind_hosts=("127.0.0.1",))
    env.system.commands.pop(TAILSCALE)
    assert "127.0.0.1,<tailscale-ip>" in env.result("bind_hosts").fix


def test_bind_hosts_refuses_lan_address(env: Env) -> None:
    env.settings = replace(env.settings, bind_hosts=("192.168.1.20",))
    assert env.result("bind_hosts").status == "fail"


def test_bind_hosts_accepts_tailscale_ipv6(env: Env) -> None:
    env.settings = replace(env.settings, bind_hosts=("::1", "fd7a:115c:a1e0::1"))
    assert env.result("bind_hosts").status == "pass"


def test_tailscale_missing(env: Env) -> None:
    env.system.commands.pop(TAILSCALE)
    result = env.result("tailscale")
    assert result.status == "fail"
    assert "Tailscale" in result.fix


def test_tailscale_bound_address_not_on_this_machine(env: Env) -> None:
    env.settings = replace(env.settings, bind_hosts=("127.0.0.1", "100.64.9.9"))
    result = env.result("tailscale")
    assert result.status == "fail"
    assert f"127.0.0.1,{TS_IP}" in result.fix


# --- database, audit chain -------------------------------------------------------------------


def test_database_missing_is_not_created(env: Env, tmp_path: Path) -> None:
    missing = tmp_path / "nested" / "none.db"
    env.settings = replace(env.settings, db_path=missing)
    results = env.results()
    assert results["database"].status == "fail"
    assert "Start-ScheduledTask" in results["database"].fix
    assert not missing.exists()
    assert not missing.parent.exists()
    assert results["audit_chain"].status == "skip"
    assert results["paired_device"].status == "skip"


def test_database_db_key_missing(env: Env) -> None:
    env.keystore.delete("db_key")
    result = env.result("database")
    assert result.status == "fail"
    assert "agent restore" in result.fix


def test_database_db_key_wrong_length(env: Env) -> None:
    env.keystore.set_bytes("db_key", b"short")
    assert env.result("database").status == "fail"


def test_database_key_does_not_match(env: Env) -> None:
    env.keystore.set_bytes("db_key", bytes(reversed(range(32))))
    result = env.result("database")
    assert result.status == "fail"
    assert "does not match" in result.detail


def test_database_not_a_database_file(env: Env) -> None:
    env.settings.db_path.write_bytes(b"this is not sqlite" * 100)
    result = env.result("database")
    assert result.status == "fail"


def test_database_empty_messages_passes(env: Env) -> None:
    db = Database(env.settings.db_path)
    db.execute("DELETE FROM messages")
    db.close()
    env.keystore.set_bytes("db_key", bytes(reversed(range(32))))
    assert env.result("database").status == "pass"


def test_audit_chain_broken(env: Env) -> None:
    db = Database(env.settings.db_path)
    db.execute(
        "INSERT INTO audit_log (ts, event, actor, action_id, detail, prev_hash, hash) "
        "VALUES ('t', 'forged', 'x', NULL, '', 'bad', 'bad')"
    )
    db.close()
    result = env.result("audit_chain")
    assert result.status == "fail"
    assert "restore" in result.fix


# --- scheduled task, power -------------------------------------------------------------------


def test_scheduled_task_missing(env: Env) -> None:
    env.system.commands.pop(SCHTASKS)
    result = env.result("scheduled_task")
    assert result.status == "fail"
    assert "install_task.ps1" in result.fix


def test_scheduled_task_not_running(env: Env) -> None:
    env.system.commands[SCHTASKS] = CommandResult(0, SCHTASKS_READY)
    result = env.result("scheduled_task")
    assert result.status == "fail"
    assert result.fix == 'Start-ScheduledTask -TaskName "PersonalAi agent"'


def test_scheduled_task_unreadable_status_warns(env: Env) -> None:
    env.system.commands[SCHTASKS] = CommandResult(0, SCHTASKS_LOCALISED)
    result = env.result("scheduled_task")
    assert (result.status, result.required) == ("warn", True)


def test_power_sleep_enabled(env: Env) -> None:
    key = ("powercfg", "/qh", "SCHEME_CURRENT", *POWERCFG["STANDBYIDLE"])
    env.system.commands[key] = CommandResult(0, powercfg_output(1800))
    result = env.result("power")
    assert result.status == "fail"
    assert result.detail.endswith("sleep on AC")
    assert result.fix.splitlines() == list(POWER_FIX_COMMANDS)


def test_power_lid_action(env: Env) -> None:
    key = ("powercfg", "/qh", "SCHEME_CURRENT", *POWERCFG["LIDACTION"])
    env.system.commands[key] = CommandResult(0, powercfg_output(1))
    assert "lid close on AC" in env.result("power").detail


def test_power_unreadable_warns(env: Env) -> None:
    key = ("powercfg", "/qh", "SCHEME_CURRENT", *POWERCFG["HIBERNATEIDLE"])
    env.system.commands.pop(key)
    assert env.result("power").status == "warn"


def test_windows_only_checks_skip_elsewhere(env: Env) -> None:
    env.system.platform = "linux"
    env.system.commands.pop(SCHTASKS)
    results = env.results()
    assert results["scheduled_task"].status == "skip"
    assert results["power"].status == "skip"


# --- paired device ---------------------------------------------------------------------------


def test_paired_device_only_revoked(env: Env) -> None:
    db = Database(env.settings.db_path)
    db.execute("UPDATE devices SET revoked = 1")
    db.close()
    result = env.result("paired_device")
    assert result.status == "fail"
    assert result.fix == "uv run python -m agent pair"


# --- freshness -------------------------------------------------------------------------------


def test_freshness_pass_details(env: Env) -> None:
    results = env.results()
    assert results["last_mail_sync"].detail.endswith("(4m ago)")
    assert results["last_sms_ingest"].detail.endswith("(2h ago)")
    assert results["last_classroom_sync"].detail.endswith("(30m ago)")


def test_freshness_stale_warns_after_three_poll_intervals(env: Env) -> None:
    env.clock.advance(timedelta(minutes=15))  # mail synced 19 minutes ago, poll is 5
    env.clock.advance(timedelta(hours=4))  # classroom 4.5h old, poll is 60 minutes
    results = env.results()
    assert results["last_mail_sync"].status == "warn"
    assert results["last_classroom_sync"].status == "warn"
    assert "stale" in results["last_mail_sync"].detail
    assert results["last_sms_ingest"].status == "pass"  # sms never goes stale


def test_freshness_never(env: Env) -> None:
    db = Database(env.settings.db_path)
    db.execute("DELETE FROM mail_accounts")
    db.execute("DELETE FROM sync_status")
    db.close()
    results = env.results()
    for check_id in ("last_mail_sync", "last_sms_ingest", "last_classroom_sync"):
        assert (results[check_id].status, results[check_id].detail) == ("warn", "never")
        assert not results[check_id].required


def test_freshness_skips_without_accounts(env: Env) -> None:
    env.settings = replace(env.settings, mail_accounts=(), classroom_accounts=())
    results = env.results()
    assert results["last_mail_sync"].status == "skip"
    assert results["last_classroom_sync"].status == "skip"


def test_mail_sync_uses_the_oldest_account(env: Env) -> None:
    env.settings = replace(env.settings, mail_accounts=(ACCOUNT, "second@example.com"))
    assert env.result("last_mail_sync").detail == "never"
    db = Database(env.settings.db_path)
    db.execute(
        "INSERT INTO mail_accounts (account, history_id, last_sync_at) VALUES (?, '1', ?)",
        ("second@example.com", (START - timedelta(minutes=1)).isoformat()),
    )
    db.close()
    assert env.result("last_mail_sync").detail.endswith("(4m ago)")


# --- crashes never leak ----------------------------------------------------------------------


def test_crashed_probe_is_a_generic_failure(env: Env) -> None:
    env.system.explode_on_http = True
    result = env.result("nvidia_models")
    assert (result.status, result.detail) == ("fail", "the check could not run")
    assert NVIDIA_KEY not in result.detail


def test_crashed_check_does_not_stop_the_others(env: Env) -> None:
    env.system.explode_on_http = True
    results = env.results()
    assert results["ollama"].status == "fail"
    assert results["power"].status == "pass"


# --- exit code, output -----------------------------------------------------------------------


def test_exit_code_one_when_a_required_check_fails(env: Env) -> None:
    env.system.programs = set()
    code, text = env.doctor()
    assert code == 1
    assert "[FAIL] uv installed: not found" in text
    assert "       fix: winget install --id=astral-sh.uv -e" in text
    assert "14/15 required checks passed. 1 failed." in text


def test_multi_line_fix_is_indented(env: Env) -> None:
    key = ("powercfg", "/qh", "SCHEME_CURRENT", *POWERCFG["LIDACTION"])
    env.system.commands[key] = CommandResult(0, powercfg_output(1))
    _, text = env.doctor()
    assert "       fix: powercfg /change standby-timeout-ac 0\n" in text
    assert "            powercfg /setactive SCHEME_CURRENT\n" in text


def test_warnings_do_not_change_the_exit_code(env: Env) -> None:
    db = Database(env.settings.db_path)
    db.execute("DELETE FROM sync_status")
    db.close()
    env.system.commands[SCHTASKS] = CommandResult(0, SCHTASKS_LOCALISED)
    code, text = env.doctor()
    assert code == 0
    assert "[WARN] Last SMS ingest: never" in text
    assert "[WARN] Scheduled task" in text


def test_skipped_required_checks_are_not_counted(env: Env) -> None:
    env.system.platform = "linux"
    code, text = env.doctor()
    assert code == 0
    assert "13/13 required checks passed." in text


def test_json_output_shape(env: Env) -> None:
    env.system.programs = set()
    code, text = env.doctor(as_json=True)
    assert code == 1
    data = json.loads(text)
    assert data["ok"] is False
    assert [c["id"] for c in data["checks"]][:3] == ["python", "uv", "keyring"]
    for check in data["checks"]:
        assert set(check) == {"id", "title", "status", "required", "detail", "fix"}
        assert check["status"] in {"pass", "fail", "warn", "skip"}
    uv = next(c for c in data["checks"] if c["id"] == "uv")
    assert uv["status"] == "fail"
    assert uv["required"] is True
    assert text.startswith("{\n  ")


def test_json_ok_when_all_pass(env: Env) -> None:
    code, text = env.doctor(as_json=True)
    assert code == 0
    assert json.loads(text)["ok"] is True


def _break_everything(env: Env) -> None:
    env.system.urls[NVIDIA_URL] = HttpResult(401)
    env.keystore.set(token_secret_name(ACCOUNT), _token(_all_scopes("gmail")))
    env.system.explode_on_http = True


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("breakage", ["healthy", "rejected", "crashed", "scopes"])
def test_secrets_never_appear_in_output(env: Env, as_json: bool, breakage: str) -> None:
    if breakage == "rejected":
        env.system.urls[NVIDIA_URL] = HttpResult(401)
    elif breakage == "crashed":
        env.system.explode_on_http = True
    elif breakage == "scopes":
        env.keystore.set(token_secret_name(ACCOUNT), _token(_all_scopes("gmail")))
    _, text = env.doctor(as_json=as_json)
    for secret in (NVIDIA_KEY, ACCESS_TOKEN, REFRESH_TOKEN):
        assert secret not in text


@pytest.mark.parametrize("as_json", [False, True])
def test_secrets_never_appear_with_everything_broken(env: Env, as_json: bool) -> None:
    _break_everything(env)
    env.keystore.delete(CLIENT_SECRET_NAME)
    _, text = env.doctor(as_json=as_json)
    for secret in (NVIDIA_KEY, ACCESS_TOKEN, REFRESH_TOKEN):
        assert secret not in text


def _record(env: Env, name: str, reason: str | None) -> None:
    db = Database(env.settings.db_path)
    if reason is None:
        record_ok(db, name, env.clock)
    else:
        record_failure(db, name, reason, env.clock)
    db.close()


def test_classroom_failure_fails_with_reason_and_google_fix(env: Env) -> None:
    _record(env, CLASSROOM, "GoogleNotConfigured for 1 of 1 accounts")
    result = env.result("last_classroom_sync")
    assert (result.status, result.required) == ("fail", False)
    assert result.detail == "GoogleNotConfigured for 1 of 1 accounts"
    assert f"setup_google_oauth.py --account {ACCOUNT}" in result.fix
    _record(env, CLASSROOM, None)
    assert env.result("last_classroom_sync").status == "pass"


def test_sms_failure_fails_with_reason_until_a_later_ok(env: Env) -> None:
    _record(env, SMS_INGEST, "none of 3 new bank messages could be parsed")
    result = env.result("last_sms_ingest")
    assert (result.status, result.required) == ("fail", False)
    assert result.detail == "none of 3 new bank messages could be parsed"
    assert result.fix
    _record(env, SMS_INGEST, None)
    assert env.result("last_sms_ingest").status == "pass"


def test_mail_failure_names_the_failing_accounts(env: Env) -> None:
    env.settings = replace(env.settings, mail_accounts=(ACCOUNT, "second@example.com"))
    _record(env, mail_status_name("second@example.com"), "GoogleNotConfigured")
    result = env.result("last_mail_sync")
    assert (result.status, result.required) == ("fail", False)
    assert result.detail == "1 of 2 accounts failing: second@example.com: GoogleNotConfigured"
    assert "setup_google_oauth.py --account second@example.com" in result.fix
    _record(env, mail_status_name("second@example.com"), None)
    assert env.result("last_mail_sync").status != "fail"


def test_mail_failure_that_is_not_a_sign_in_problem_points_to_the_log(env: Env) -> None:
    _record(env, mail_status_name(ACCOUNT), "TimeoutError")
    result = env.result("last_mail_sync")
    assert result.status == "fail"
    assert "log" in result.fix
