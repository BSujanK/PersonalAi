"""``agent doctor``: checks every go-live prerequisite and prints the exact fix for each failure.

Read-only: nothing here changes the machine, the database or the keyring. Each check catches its
own exceptions and reports a generic failure, because exception text can carry paths or secrets.
Details name variables, models, services and counts, never keys, tokens or content.
"""

from __future__ import annotations

import functools
import ipaddress
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, TextIO

import keyring

from agent.config import Settings
from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    DRIVE_FILE,
    SERVICE_SCOPES,
    granted_scopes,
    token_secret_name,
)
from agent.core.audit import AuditLog
from agent.core.clock import Clock
from agent.core.llm import require_loopback
from agent.core.netguard import validate_bind_hosts
from agent.golive import probes, service
from agent.golive.system import System
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.devices import list_devices
from agent.store.keystore import KeyStore, assert_secure_backend
from agent.store.sync_status import CLASSROOM, MAIL, SMS_INGEST, last_failure, last_ok

Status = Literal["pass", "fail", "warn", "skip"]

NVIDIA_KEY_NAME = "nvidia_api_key"
DB_KEY_NAME = "db_key"
_CRASHED = "the check could not run"
_TAILSCALE_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)
_STALE_FACTOR = 3
AGENT_DIR = Path(__file__).resolve().parents[1]  # server/agent: the code the server runs
_GOOGLE_FIX = (
    "fix the Google account checks above (token missing or scopes), "
    "then restart: uv run python -m agent restart"
)


@dataclass(frozen=True)
class CheckResult:
    id: str
    title: str
    status: Status
    required: bool
    detail: str
    fix: str = ""


@dataclass
class _Ctx:
    settings: Settings
    system: System
    keystore: KeyStore
    clock: Clock
    db: Database | None
    code_dir: Path

    @property
    def is_windows(self) -> bool:
        return self.system.platform == "win32"


_Check = Callable[[_Ctx], CheckResult | list[CheckResult]]


def _guard(
    check_id: str, title: str, required: bool = True
) -> Callable[[Callable[[_Ctx], CheckResult | list[CheckResult]]], _Check]:
    """A crashed check is a failure with a generic detail, never a traceback."""

    def decorate(fn: Callable[[_Ctx], CheckResult | list[CheckResult]]) -> _Check:
        @functools.wraps(fn)
        def run(ctx: _Ctx) -> CheckResult | list[CheckResult]:
            try:
                return fn(ctx)
            except Exception:
                return CheckResult(check_id, title, "fail", required, _CRASHED)

        return run

    return decorate


def _set_env(name: str, value: str) -> str:
    return f'[Environment]::SetEnvironmentVariable("{name}", "{value}", "User")'


def _skip_non_windows(check_id: str, title: str, required: bool = True) -> CheckResult:
    return CheckResult(check_id, title, "skip", required, "Windows only")


@_guard("python", "Python")
def _check_python(ctx: _Ctx) -> CheckResult:
    major, minor, micro = ctx.system.python_version()
    title = f"Python {major}.{minor}.{micro}"
    if (major, minor) >= (3, 12):
        return CheckResult("python", title, "pass", True, "")
    return CheckResult(
        "python",
        title,
        "fail",
        True,
        "Python 3.12 or newer is required",
        "install Python 3.12+ from https://www.python.org/downloads/",
    )


@_guard("uv", "uv installed")
def _check_uv(ctx: _Ctx) -> CheckResult:
    if ctx.system.which("uv"):
        return CheckResult("uv", "uv installed", "pass", True, "")
    return CheckResult(
        "uv", "uv installed", "fail", True, "not found", "winget install --id=astral-sh.uv -e"
    )


def _backend_names(backend: object) -> list[str]:
    members = getattr(backend, "backends", None)
    if members:
        return [type(m).__name__ for m in members]
    return [type(backend).__name__]


@_guard("keyring", "OS keyring backend")
def _check_keyring(ctx: _Ctx) -> CheckResult:
    title = "OS keyring backend"
    fix = "see docs/SETUP.md, step A1.3 (the keyring backend)"
    active = keyring.get_keyring()
    names = _backend_names(active)
    detail = type(active).__name__
    try:
        assert_secure_backend(active)
    except Exception:
        return CheckResult("keyring", title, "fail", True, f"{detail} is not a secure backend", fix)
    if not ctx.is_windows:
        return CheckResult("keyring", title, "pass", True, f"{detail} (Windows Vault not checked)")
    if "WinVaultKeyring" not in names:
        return CheckResult(
            "keyring", title, "fail", True, f"{detail} is not Windows Credential Manager", fix
        )
    return CheckResult("keyring", title, "pass", True, detail)


@_guard("nvidia_key", "NVIDIA key in keyring")
def _check_nvidia_key(ctx: _Ctx) -> CheckResult:
    title = "NVIDIA key in keyring"
    if ctx.keystore.get(NVIDIA_KEY_NAME):
        return CheckResult("nvidia_key", title, "pass", True, "set")
    return CheckResult(
        "nvidia_key",
        title,
        "fail",
        True,
        "not set",
        "uv run python -m agent setup\n"
        f"(or) uv run python -m keyring set PersonalAi {NVIDIA_KEY_NAME}",
    )


@_guard("nvidia_models", "NVIDIA models")
def _check_nvidia_models(ctx: _Ctx) -> CheckResult:
    title = "NVIDIA models"
    key = ctx.keystore.get(NVIDIA_KEY_NAME)
    if not key:
        return CheckResult("nvidia_models", title, "skip", True, "no NVIDIA key")
    listing = probes.nvidia_models(ctx.system, ctx.settings.nvidia_base_url, key)
    list_cmd = "uv run python scripts/eval_models.py --list-models"
    if listing.status == 0:
        return CheckResult(
            "nvidia_models", title, "fail", True, "NVIDIA Build is unreachable", "check internet"
        )
    if listing.status in (401, 403):
        return CheckResult(
            "nvidia_models",
            title,
            "fail",
            True,
            "the NVIDIA key was rejected",
            "uv run python -m agent setup",
        )
    if listing.status != 200:
        return CheckResult(
            "nvidia_models", title, "fail", True, f"unexpected response (HTTP {listing.status})"
        )
    wanted = (
        ("PERSONALAI_MODEL_PRIMARY", ctx.settings.model_primary, True),
        *(("PERSONALAI_MODEL_FALLBACK", m, False) for m in ctx.settings.model_fallbacks),
        ("PERSONALAI_MODEL_LONG", ctx.settings.model_long, False),
    )
    problems: list[str] = []
    fixes = [list_cmd]
    for variable, model, mandatory in wanted:
        if not model:
            if mandatory:
                problems.append(f"{variable} is not set")
                fixes.append(_set_env(variable, "<model-id>"))
        elif model not in listing.ids:
            problems.append(f"{variable}={model} is not offered")
            fixes.append(_set_env(variable, "<model-id>"))
    if problems:
        return CheckResult(
            "nvidia_models", title, "fail", True, "; ".join(problems), "\n".join(fixes)
        )
    configured = [m for _, m, _ in wanted if m]
    return CheckResult("nvidia_models", title, "pass", True, ", ".join(configured))


@_guard("ollama", "Ollama")
def _check_ollama(ctx: _Ctx) -> CheckResult:
    title = "Ollama"
    try:
        require_loopback(ctx.settings.ollama_base_url)
    except ValueError:
        return CheckResult(
            "ollama",
            title,
            "fail",
            True,
            "the Ollama base URL is not a loopback address",
            "unset OLLAMA_HOST so Ollama listens on 127.0.0.1:11434",
        )
    pulled = probes.ollama_models(ctx.system, ctx.settings.ollama_base_url)
    if pulled is None:
        return CheckResult(
            "ollama", title, "fail", True, "Ollama does not answer", "start Ollama (ollama serve)"
        )
    wanted = list(dict.fromkeys((ctx.settings.classifier_model, ctx.settings.ollama_model)))
    missing = [m for m in wanted if not probes.has_model(pulled, m)]
    if missing:
        return CheckResult(
            "ollama",
            title,
            "fail",
            True,
            "not pulled: " + ", ".join(missing),
            "\n".join(f"ollama pull {m}" for m in missing),
        )
    return CheckResult("ollama", title, "pass", True, "models present: " + ", ".join(wanted))


@_guard("ollama_context", "Ollama context length")
def _check_ollama_context(ctx: _Ctx) -> CheckResult:
    title = "Ollama context length"
    need = ctx.settings.local_context_tokens
    fix = (
        f"{_set_env('OLLAMA_CONTEXT_LENGTH', str(need))}\n"
        "then quit Ollama from the tray and start it again"
    )
    raw = ctx.system.user_env("OLLAMA_CONTEXT_LENGTH")
    if raw is None or not raw.strip():
        return CheckResult(
            "ollama_context", title, "fail", True, "OLLAMA_CONTEXT_LENGTH not set", fix
        )
    try:
        value = int(raw.strip())
    except ValueError:
        return CheckResult(
            "ollama_context", title, "fail", True, "OLLAMA_CONTEXT_LENGTH is not a number", fix
        )
    if value < need:
        return CheckResult(
            "ollama_context",
            title,
            "fail",
            True,
            f"OLLAMA_CONTEXT_LENGTH={value}, needs at least {need}",
            fix,
        )
    return CheckResult("ollama_context", title, "pass", True, f"{value} (needs {need})")


def _services_for(settings: Settings, account: str) -> list[str]:
    configured = {
        "gmail": settings.mail_accounts,
        "calendar": settings.calendar_accounts,
        "classroom": settings.classroom_accounts,
        "drive": settings.drive_accounts,
    }
    return [s for s, accounts in configured.items() if account in {a.lower() for a in accounts}]


def _check_google_account(ctx: _Ctx, account: str) -> CheckResult:
    check_id, title = f"google:{account}", f"Google account {account}"
    try:
        services = _services_for(ctx.settings, account)
        if not ctx.keystore.get(CLIENT_SECRET_NAME):
            return CheckResult(
                check_id,
                title,
                "fail",
                True,
                "OAuth client not in keyring",
                f"uv run python scripts/setup_google_oauth.py --account {account} "
                f"--services {','.join(services)}",
            )
        token_raw = ctx.keystore.get(token_secret_name(account))
        token = json.loads(token_raw) if token_raw else None
        if not isinstance(token, dict) or not token.get("refresh_token"):
            return CheckResult(
                check_id,
                title,
                "fail",
                True,
                "no usable token (missing or no refresh token)",
                f"uv run python scripts/setup_google_oauth.py --account {account} "
                f"--services {','.join(services)}",
            )
        granted = granted_scopes(token_raw)
        ok = [s for s in services if set(SERVICE_SCOPES[s]) <= granted]
        missing = [s for s in services if s not in ok]
        if missing:
            detail = f"granted: {', '.join(ok) or 'none'}; missing: {', '.join(missing)}"
            if "drive" in missing and DRIVE_FILE in granted:
                detail += (
                    " (Drive now needs full Drive access so drive_share can share existing "
                    "files; re-consent once)"
                )
            return CheckResult(
                check_id,
                title,
                "fail",
                True,
                detail,
                f"uv run python scripts/setup_google_oauth.py --account {account} "
                f"--services {','.join(missing)}",
            )
        return CheckResult(check_id, title, "pass", True, "granted: " + ", ".join(services))
    except Exception:
        return CheckResult(check_id, title, "fail", True, _CRASHED)


@_guard("google", "Google accounts", required=False)
def _check_google(ctx: _Ctx) -> list[CheckResult]:
    accounts = ctx.settings.google_accounts
    if not accounts:
        return [
            CheckResult(
                "google",
                "Google accounts",
                "warn",
                False,
                "no Google accounts configured",
                "set PERSONALAI_MAIL_ACCOUNTS (and the calendar, classroom, drive variables)",
            )
        ]
    return [_check_google_account(ctx, a) for a in accounts]


def _is_tailscale(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(addr in net for net in _TAILSCALE_NETS)


@_guard("bind_hosts", "Bind addresses")
def _check_bind_hosts(ctx: _Ctx) -> CheckResult:
    title = "Bind addresses"
    try:
        hosts = validate_bind_hosts(ctx.settings.bind_hosts)
    except ValueError:
        return CheckResult(
            "bind_hosts",
            title,
            "fail",
            True,
            "a configured address is not loopback or Tailscale",
            _set_env("PERSONALAI_BIND_HOSTS", "127.0.0.1"),
        )
    if any(_is_tailscale(h) for h in hosts):
        return CheckResult("bind_hosts", title, "pass", True, ", ".join(map(str, hosts)))
    found = probes.tailscale_ipv4(ctx.system)
    return CheckResult(
        "bind_hosts",
        title,
        "fail",
        True,
        "no Tailscale address is bound, so the phone cannot connect",
        _set_env("PERSONALAI_BIND_HOSTS", f"127.0.0.1,{found[0] if found else '<tailscale-ip>'}"),
    )


@_guard("tailscale", "Tailscale")
def _check_tailscale(ctx: _Ctx) -> CheckResult:
    title = "Tailscale"
    found = probes.tailscale_ipv4(ctx.system)
    if not found:
        return CheckResult(
            "tailscale",
            title,
            "fail",
            True,
            "no Tailscale address on this machine",
            "install Tailscale from https://tailscale.com/download and sign in",
        )
    bound: list[str] = []
    for host in ctx.settings.bind_hosts:
        try:
            addr = ipaddress.ip_address(host.strip().strip("[]"))
        except ValueError:
            continue
        if addr.version == 4 and _is_tailscale(addr):
            bound.append(str(addr))
    if bound and not set(bound) & set(found):
        return CheckResult(
            "tailscale",
            title,
            "fail",
            True,
            f"bound {', '.join(bound)} is not this machine's address ({', '.join(found)})",
            _set_env("PERSONALAI_BIND_HOSTS", f"127.0.0.1,{found[0]}"),
        )
    return CheckResult("tailscale", title, "pass", True, ", ".join(found))


@_guard("database", "Database")
def _check_database(ctx: _Ctx) -> CheckResult:
    title = "Database"
    restore = "stop the server, then: uv run python -m agent restore --in <backup file> --force"
    if not Path(ctx.settings.db_path).exists():
        return CheckResult(
            "database",
            title,
            "fail",
            True,
            "database file not found",
            "start the server once: uv run python -m agent restart",
        )
    key = ctx.keystore.get_bytes(DB_KEY_NAME)
    if key is None or len(key) != 32:
        return CheckResult(
            "database",
            title,
            "fail",
            True,
            "db_key is missing or malformed in the keyring",
            restore,
        )
    if ctx.db is None:
        return CheckResult("database", title, "fail", True, "database cannot be opened", restore)
    rows = ctx.db.query("SELECT id, content_enc FROM messages LIMIT 1")
    if rows:
        row = rows[0]
        try:
            FieldCipher(key).decrypt_str(row["content_enc"], f"messages.content:{row['id']}")
        except Exception:
            return CheckResult(
                "database", title, "fail", True, "db_key does not match this database", restore
            )
    return CheckResult("database", title, "pass", True, "opens and decrypts")


@_guard("audit_chain", "Audit log chain")
def _check_audit(ctx: _Ctx) -> CheckResult:
    title = "Audit log chain"
    if ctx.db is None:
        return CheckResult("audit_chain", title, "skip", True, "no database")
    if AuditLog(ctx.db, ctx.clock).verify():
        return CheckResult("audit_chain", title, "pass", True, "intact")
    return CheckResult(
        "audit_chain",
        title,
        "fail",
        True,
        "the hash chain is broken (tampering or a damaged database)",
        "restore the latest backup: uv run python -m agent restore --in <backup file> --force",
    )


@_guard("scheduled_task", "Scheduled task")
def _check_task(ctx: _Ctx) -> CheckResult:
    title = "Scheduled task"
    if not ctx.is_windows:
        return _skip_non_windows("scheduled_task", title)
    state = probes.scheduled_task(ctx.system)
    if not state.exists:
        return CheckResult(
            "scheduled_task",
            title,
            "fail",
            True,
            f'task "{probes.TASK_NAME}" is not installed',
            "powershell -ExecutionPolicy Bypass -File scripts\\install_task.ps1",
        )
    if state.status is None:
        return CheckResult(
            "scheduled_task", title, "warn", True, "installed, but its state could not be read"
        )
    if state.status != "Running":
        return CheckResult(
            "scheduled_task",
            title,
            "fail",
            True,
            f"installed but {state.status}",
            "uv run python -m agent restart",
        )
    return CheckResult("scheduled_task", title, "pass", True, "Running")


_TASK_RUNNING = 0x41301  # SCHED_S_TASK_RUNNING
_TASK_NOT_YET_RUN = 0x41303  # SCHED_S_TASK_HAS_NOT_RUN
_CONTROL_C_EXIT = 0xC000013A  # STATUS_CONTROL_C_EXIT: the console was closed or got Ctrl+C
_REINSTALL = (
    "powershell -ExecutionPolicy Bypass -File scripts\\install_task.ps1\n"
    "uv run python -m agent restart"
)


@_guard("task_last_result", "Scheduled task last result", required=False)
def _check_task_last_result(ctx: _Ctx) -> CheckResult:
    title = "Scheduled task last result"
    if not ctx.is_windows:
        return _skip_non_windows("task_last_result", title, required=False)
    run = probes.scheduled_task_run(ctx.system)
    if run is None:
        return CheckResult(
            "task_last_result", title, "skip", False, "task not installed or not readable"
        )
    command = (run.command or "").lower()
    if "powershell" in command or "run_agent.ps1" in command:
        return CheckResult(
            "task_last_result",
            title,
            "warn",
            False,
            "the task still uses the old PowerShell launcher, which a console close or Ctrl+C "
            "event at logon can kill",
            "reinstall the task to get the console-less launcher:\n" + _REINSTALL,
        )
    code = run.last_result
    if code is None:
        return CheckResult("task_last_result", title, "warn", False, "last result not readable")
    if code == 0:
        return CheckResult("task_last_result", title, "pass", False, "last run exited 0")
    if code == _TASK_RUNNING:
        return CheckResult("task_last_result", title, "pass", False, "running now")
    if code == _TASK_NOT_YET_RUN:
        return CheckResult("task_last_result", title, "skip", False, "the task has not run yet")
    if code == _CONTROL_C_EXIT:
        return CheckResult(
            "task_last_result",
            title,
            "fail",
            False,
            "0xC000013A: the server was killed by a console close or Ctrl+C event",
            "reinstall the task so it runs without a console:\n" + _REINSTALL,
        )
    return CheckResult(
        "task_last_result",
        title,
        "fail",
        False,
        f"last run exited with 0x{code:08X}",
        "see agent.log next to the database (default %USERPROFILE%\\.personalai\\agent.log), "
        "then: uv run python -m agent restart",
    )


@_guard("server_code", "Running server is current", required=False)
def _check_server_code(ctx: _Ctx) -> CheckResult:
    """Warn when the running server started before the newest source file was modified."""
    title = "Running server is current"
    if not ctx.is_windows:
        return _skip_non_windows("server_code", title, required=False)
    procs = service.find_server_processes(ctx.system)
    if procs is None:
        return CheckResult("server_code", title, "warn", False, "could not list processes")
    if not procs:
        return CheckResult("server_code", title, "skip", False, "no running server process")
    started = min(p.started for p in procs)
    newest = service.newest_source_mtime(ctx.code_dir)
    when = started.isoformat(timespec="minutes")
    if newest is not None and newest > started:
        return CheckResult(
            "server_code",
            title,
            "warn",
            False,
            f"the server started {when}, before its code changed "
            f"({newest.isoformat(timespec='minutes')}): it is running stale code",
            "uv run python -m agent restart",
        )
    return CheckResult("server_code", title, "pass", False, f"started {when}")


@_guard("power", "Power settings")
def _check_power(ctx: _Ctx) -> CheckResult:
    title = "Power settings"
    if not ctx.is_windows:
        return _skip_non_windows("power", title)
    power = probes.power_settings(ctx.system)
    values = (
        ("sleep on AC", power.standby_ac),
        ("hibernate on AC", power.hibernate_ac),
        ("lid close on AC", power.lid_ac),
    )
    if any(v is None for _, v in values):
        return CheckResult("power", title, "warn", True, "powercfg could not be read")
    if power.ok:
        return CheckResult("power", title, "pass", True, "never sleeps on AC, lid does nothing")
    bad = [name for name, v in values if v != 0]
    return CheckResult(
        "power",
        title,
        "fail",
        True,
        "the laptop would stop serving: " + ", ".join(bad),
        "\n".join(probes.POWER_FIX_COMMANDS),
    )


@_guard("paired_device", "Paired phone")
def _check_paired(ctx: _Ctx) -> CheckResult:
    title = "Paired phone"
    if ctx.db is None:
        return CheckResult("paired_device", title, "skip", True, "no database")
    active = [d for d in list_devices(ctx.db) if not d["revoked"]]
    if active:
        return CheckResult("paired_device", title, "pass", True, f"{len(active)} active device(s)")
    return CheckResult(
        "paired_device", title, "fail", True, "no paired device", "uv run python -m agent pair"
    )


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _age_text(age: timedelta) -> str:
    minutes = max(int(age.total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 60 * 48:
        return f"{minutes // 60}h"
    return f"{minutes // (60 * 24)}d"


def _freshness(
    check_id: str,
    title: str,
    last: datetime | None,
    now: datetime,
    poll_minutes: int | None,
) -> CheckResult:
    if last is None:
        return CheckResult(check_id, title, "warn", False, "never")
    last = _aware(last)
    age = now - last
    detail = f"{last.isoformat(timespec='minutes')} ({_age_text(age)} ago)"
    if poll_minutes is not None and age > timedelta(minutes=poll_minutes * _STALE_FACTOR):
        return CheckResult(check_id, title, "warn", False, f"stale: {detail}")
    return CheckResult(check_id, title, "pass", False, detail)


def _with_failure(ctx: _Ctx, name: str, result: CheckResult, fix: str) -> CheckResult:
    """Override a freshness result when the source's latest run is recorded as failed."""
    failure = last_failure(ctx.db, name) if ctx.db is not None else None
    if failure is None:
        return result
    when = _aware(failure.at).isoformat(timespec="minutes")
    detail = f"{failure.reason} ({when}; last OK: {result.detail})"
    if failure.partial:
        return CheckResult(result.id, result.title, "warn", False, "partly failing: " + detail)
    return CheckResult(
        result.id,
        result.title,
        "fail",
        False,
        "failing: " + detail,
        fix,
    )


def _mail_last_sync(ctx: _Ctx) -> datetime | None:
    """The oldest per-account sync time; ``None`` if any configured account never synced."""
    if ctx.db is None:
        return None
    oldest: datetime | None = None
    for account in ctx.settings.mail_accounts:
        rows = ctx.db.query("SELECT last_sync_at FROM mail_accounts WHERE account = ?", (account,))
        if not rows or not rows[0]["last_sync_at"]:
            return None
        moment = _aware(datetime.fromisoformat(rows[0]["last_sync_at"]))
        oldest = moment if oldest is None else min(oldest, moment)
    return oldest


@_guard("last_mail_sync", "Last mail sync", required=False)
def _check_mail_sync(ctx: _Ctx) -> CheckResult:
    title = "Last mail sync"
    if not ctx.settings.mail_accounts:
        return CheckResult("last_mail_sync", title, "skip", False, "no mail accounts")
    return _with_failure(
        ctx,
        MAIL,
        _freshness(
            "last_mail_sync",
            title,
            _mail_last_sync(ctx),
            ctx.clock(),
            ctx.settings.mail_poll_minutes,
        ),
        _GOOGLE_FIX,
    )


@_guard("last_sms_ingest", "Last SMS ingest", required=False)
def _check_sms(ctx: _Ctx) -> CheckResult:
    title = "Last SMS ingest"
    last = last_ok(ctx.db, SMS_INGEST) if ctx.db is not None else None
    return _with_failure(
        ctx,
        SMS_INGEST,
        _freshness("last_sms_ingest", title, last, ctx.clock(), None),
        "the phone sent bank SMS the parsers cannot read: check the sender and format of "
        "unparsed messages (see docs/SETUP.md)",
    )


@_guard("last_classroom_sync", "Last Classroom sync", required=False)
def _check_classroom(ctx: _Ctx) -> CheckResult:
    title = "Last Classroom sync"
    if not ctx.settings.classroom_accounts:
        return CheckResult("last_classroom_sync", title, "skip", False, "no Classroom accounts")
    last = last_ok(ctx.db, CLASSROOM) if ctx.db is not None else None
    return _with_failure(
        ctx,
        CLASSROOM,
        _freshness(
            "last_classroom_sync", title, last, ctx.clock(), ctx.settings.deadline_poll_minutes
        ),
        _GOOGLE_FIX,
    )


_CHECKS: tuple[_Check, ...] = (
    _check_python,
    _check_uv,
    _check_keyring,
    _check_nvidia_key,
    _check_nvidia_models,
    _check_ollama,
    _check_ollama_context,
    _check_google,
    _check_bind_hosts,
    _check_tailscale,
    _check_database,
    _check_audit,
    _check_task,
    _check_task_last_result,
    _check_server_code,
    _check_power,
    _check_paired,
    _check_mail_sync,
    _check_sms,
    _check_classroom,
)


def _open_existing_db(path: Path) -> Database | None:
    """Open the database only if it already exists; doctor never creates one."""
    if not Path(path).exists():
        return None
    try:
        return Database(path)
    except Exception:
        return None


def run_checks(
    settings: Settings,
    system: System,
    keystore: KeyStore,
    *,
    clock: Clock,
    code_dir: Path = AGENT_DIR,
) -> list[CheckResult]:
    ctx = _Ctx(settings, system, keystore, clock, _open_existing_db(settings.db_path), code_dir)
    results: list[CheckResult] = []
    try:
        for check in _CHECKS:
            outcome = check(ctx)
            results.extend(outcome if isinstance(outcome, list) else [outcome])
    finally:
        if ctx.db is not None:
            ctx.db.close()
    return results


def _render(results: list[CheckResult]) -> list[str]:
    lines = ["PersonalAi doctor"]
    for r in results:
        text = f"{r.title}: {r.detail}" if r.detail else r.title
        lines.append(f"[{r.status.upper()}] {text}")
        for index, fix_line in enumerate(r.fix.splitlines()):
            prefix = "fix: " if index == 0 else "     "
            lines.append(f"       {prefix}{fix_line}")
    required = [r for r in results if r.required and r.status != "skip"]
    passed = sum(1 for r in required if r.status != "fail")
    failed = len(required) - passed
    summary = f"{passed}/{len(required)} required checks passed."
    lines.append(summary + (f" {failed} failed." if failed else ""))
    return lines


def run_doctor(
    settings: Settings,
    system: System,
    keystore: KeyStore,
    *,
    as_json: bool,
    out: TextIO,
    clock: Clock,
    code_dir: Path = AGENT_DIR,
) -> int:
    results = run_checks(settings, system, keystore, clock=clock, code_dir=code_dir)
    ok = not any(r.required and r.status == "fail" for r in results)
    if as_json:
        out.write(json.dumps({"ok": ok, "checks": [asdict(r) for r in results]}, indent=2) + "\n")
    else:
        out.write("\n".join(_render(results)) + "\n")
    return 0 if ok else 1
