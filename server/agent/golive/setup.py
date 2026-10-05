"""``python -m agent setup``: an interactive go-live wizard that walks through docs/SETUP.md.

Every step looks at the real system first and skips itself when it is already done, so the wizard
can be stopped and run again. Anything that changes the system asks first. Secrets (the NVIDIA key)
go only from a hidden prompt into the OS keyring: never into argv, the environment or output.
"""

from __future__ import annotations

import getpass
import os
import re
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from agent.config import Settings
from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    SERVICE_SCOPES,
    granted_scopes,
    scopes_for,
    token_secret_name,
)
from agent.core.netguard import UnsafeBindAddress, validate_bind_hosts
from agent.golive import probes
from agent.golive.system import System
from agent.store.keystore import KeyStore

NVIDIA_KEY_NAME = "nvidia_api_key"
STEP_IDS = (
    "prereqs",
    "nvidia_key",
    "models",
    "ollama",
    "google",
    "profile",
    "network",
    "task",
    "power",
    "pair",
)
_TOTAL = len(STEP_IDS)
_ACCOUNT_ENV = {
    "gmail": "PERSONALAI_MAIL_ACCOUNTS",
    "calendar": "PERSONALAI_CALENDAR_ACCOUNTS",
    "classroom": "PERSONALAI_CLASSROOM_ACCOUNTS",
    "drive": "PERSONALAI_DRIVE_ACCOUNTS",
}
_KNOWN_ENV = (
    "PERSONALAI_DB_PATH",
    "PERSONALAI_PORT",
    "PERSONALAI_BIND_HOSTS",
    "PERSONALAI_MODEL_PRIMARY",
    "PERSONALAI_MODEL_FALLBACK",
    "PERSONALAI_MODEL_LONG",
    "PERSONALAI_LONG_CONTEXT_TOKENS",
    "PERSONALAI_LOCAL_CONTEXT_TOKENS",
    "PERSONALAI_CLASSIFIER_MODEL",
    "PERSONALAI_OWNER_EMAILS",
    "PERSONALAI_VIP_SENDERS",
    "PERSONALAI_COLLEGE_DOMAINS",
    "PERSONALAI_FILE_ROOTS",
    "OLLAMA_CONTEXT_LENGTH",
    *_ACCOUNT_ENV.values(),
)
_ADDRESS = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")
_DEFAULT_LOCAL_CONTEXT = 8192
_MAX_TRIES = 3


class Prompter(Protocol):
    def ask(self, question: str, default: str = "") -> str: ...

    def secret(self, question: str) -> str: ...

    def confirm(self, question: str, default: bool = True) -> bool: ...

    def say(self, text: str) -> None: ...


class ConsolePrompter:
    """Terminal prompts. Hidden input uses ``getpass``; nothing typed is echoed back."""

    def ask(self, question: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = input(f"{question}{suffix}: ").strip()
        return answer or default

    def secret(self, question: str) -> str:
        return getpass.getpass(f"{question}: ").strip()

    def confirm(self, question: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = input(f"{question} [{hint}] ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

    def say(self, text: str) -> None:
        try:
            print(text)
        except UnicodeEncodeError:
            encoding = sys.stdout.encoding or "ascii"
            print(text.encode(encoding, errors="replace").decode(encoding))


class _Stop(Exception):
    """End the wizard with this exit code (a message has already been shown)."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _split(value: str, sep: str = ",") -> list[str]:
    return [part.strip() for part in value.split(sep) if part.strip()]


def _positive_int(text: str) -> int | None:
    try:
        number = int(text.strip())
    except ValueError:
        return None
    return number if number > 0 else None


class _Wizard:
    def __init__(
        self,
        system: System,
        prompter: Prompter,
        keystore: KeyStore,
        server_dir: Path,
        run_doctor: Callable[[], int],
        open_pairing: Callable[[], None],
        redo: frozenset[str],
    ) -> None:
        self.system = system
        self.p = prompter
        self.keystore = keystore
        self.server_dir = server_dir
        self.run_doctor = run_doctor
        self.open_pairing = open_pairing
        self.redo = redo
        self.written: dict[str, str] = {}

    # --- shared helpers -------------------------------------------------------------------

    def _env_value(self, name: str) -> str | None:
        if name in self.written:
            return self.written[name]
        value = self.system.user_env(name)
        return value if value is not None else os.environ.get(name)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        for name in _KNOWN_ENV:
            value = self._env_value(name)
            if value is not None:
                env[name] = value
        return env

    def _settings(self) -> Settings:
        try:
            return Settings.from_env(self._env())
        except ValueError as exc:
            self.p.say(f"A PERSONALAI_* setting is invalid: {exc}. Fix it and run setup again.")
            raise _Stop(2) from exc

    def _skip_done(self, step: str, label: str, why: str) -> bool:
        """True (after saying so) when the step is already done and not being redone."""
        if step in self.redo:
            return False
        self.p.say(f"✓ {label}: already done ({why})")
        return True

    def _header(self, number: int, title: str) -> None:
        self.p.say(f"[{number}/{_TOTAL}] {title}")

    def _write_env(self, items: Mapping[str, str], question: str = "Save these?") -> bool:
        for name, value in items.items():
            self.p.say(f"  {name}={value}")
        if not self.p.confirm(question, True):
            self.p.say("Not changed.")
            return False
        for name, value in items.items():
            self.system.set_user_env(name, value)
            self.written[name] = value
        return True

    def _ask_valid(
        self, question: str, check: Callable[[str], str | None], default: str = ""
    ) -> str | None:
        """Ask until ``check`` returns no complaint; ``None`` after a few failed tries."""
        for _ in range(_MAX_TRIES):
            answer = self.p.ask(question, default)
            problem = check(answer)
            if problem is None:
                return answer
            self.p.say(problem)
        self.p.say("Too many invalid answers; skipping this step.")
        return None

    # --- steps ----------------------------------------------------------------------------

    def prereqs(self) -> None:
        self._header(1, "Prerequisites")
        major, minor, _ = self.system.python_version()
        if (major, minor) < (3, 12):
            self.p.say(f"Python 3.12 or newer is required (this is {major}.{minor}).")
            raise _Stop(2)
        if self.system.which("uv") is None:
            self.p.say("uv is not installed. Install it, then run setup again:")
            self.p.say("  winget install --id=astral-sh.uv -e")
            raise _Stop(2)
        if (self.server_dir / ".venv").is_dir() and "prereqs" not in self.redo:
            self.p.say("✓ Prerequisites: already done (Python, uv and the environment are ready)")
            return
        if not self.p.confirm("Run uv sync now?", True):
            return
        code = self.system.run_interactive(["uv", "sync", "--directory", str(self.server_dir)])
        if code != 0:
            self.p.say(f"uv sync failed (exit {code}). Fix that and run setup again.")
            raise _Stop(2)

    def nvidia_key(self) -> None:
        self._header(2, "NVIDIA API key")
        if self.keystore.get(NVIDIA_KEY_NAME) is not None and "nvidia_key" not in self.redo:
            self.p.say("✓ NVIDIA API key: already done (stored in the keyring)")
            return
        key = ""
        for _ in range(2):
            key = self.p.secret("NVIDIA API key (input hidden)")
            if key:
                break
            self.p.say("No key entered.")
        if not key:
            self.p.say("Skipped: run setup again when you have a key.")
            return
        if not key.startswith("nvapi-"):
            self.p.say("Warning: NVIDIA keys normally start with 'nvapi-'. Check you copied it.")
        if not self.p.confirm("Store the key in the OS keyring?", True):
            self.p.say("Not stored.")
            return
        self.keystore.set(NVIDIA_KEY_NAME, key)
        self.p.say("Key stored in the keyring.")

    def models(self) -> None:
        self._header(3, "Models")
        settings = self._settings()
        if settings.model_primary and "models" not in self.redo:
            self.p.say(
                f"✓ Models: already done (PERSONALAI_MODEL_PRIMARY={settings.model_primary})"
            )
            return
        key = self.keystore.get(NVIDIA_KEY_NAME)
        if key is None:
            self.p.say("Skipped: no NVIDIA API key is stored yet.")
            return
        listing = probes.nvidia_models(self.system, settings.nvidia_base_url, key)
        if not listing.ids:
            status = listing.status or "unreachable"
            self.p.say(f"Could not list the NVIDIA models (status: {status}); skipping.")
            return
        ids = listing.ids
        for number, model in enumerate(ids, 1):
            self.p.say(f"  {number:>3}. {model}")
        self._maybe_eval(ids)

        def known(text: str) -> str | None:
            return None if text in ids else "Not one of the listed model ids."

        def optional(text: str) -> str | None:
            return None if not text else known(text)

        primary = self._ask_valid("PRIMARY model id (required)", known)
        if primary is None:
            return
        fallback = self._ask_valid("FALLBACK model id (optional)", optional)
        long_model = self._ask_valid("LONG-context model id (optional)", optional)

        def tokens(text: str) -> str | None:
            if not text or _positive_int(text) is not None:
                return None
            return "Enter a positive whole number."

        long_tokens = self._ask_valid("Long-context token limit (optional)", tokens)
        values = {"PERSONALAI_MODEL_PRIMARY": primary}
        if fallback:
            values["PERSONALAI_MODEL_FALLBACK"] = fallback
        if long_model:
            values["PERSONALAI_MODEL_LONG"] = long_model
        if long_tokens:
            values["PERSONALAI_LONG_CONTEXT_TOKENS"] = str(int(long_tokens))
        self._write_env(values, "Save these model settings?")

    def _maybe_eval(self, ids: Sequence[str]) -> None:
        if not self.p.confirm("Run scripts/eval_models.py on some of them?", False):
            return

        def check(text: str) -> str | None:
            chosen = _split(text)
            bad = [m for m in chosen if m not in ids]
            return f"Not listed: {', '.join(bad)}" if bad else None

        answer = self._ask_valid("Model ids to evaluate (comma-separated, blank to skip)", check)
        chosen = _split(answer or "")
        if not chosen:
            return
        code = self.system.run_interactive(
            [
                "uv",
                "run",
                "--directory",
                str(self.server_dir),
                "python",
                "scripts/eval_models.py",
                *chosen,
            ]
        )
        if code != 0:
            self.p.say(f"The evaluation exited with code {code}; carry on and choose anyway.")

    def ollama(self) -> None:
        self._header(4, "Local model (Ollama)")
        settings = self._settings()
        pulled = probes.ollama_models(self.system, settings.ollama_base_url)
        if pulled is None:
            self.p.say("Ollama is not answering. Install or start it (https://ollama.com/download)")
            self.p.say("and run setup again. Skipping this step.")
            return
        wanted = list(dict.fromkeys([settings.classifier_model, settings.ollama_model]))
        missing = [m for m in wanted if not probes.has_model(pulled, m)]
        current = _positive_int(self._env_value("OLLAMA_CONTEXT_LENGTH") or "") or 0
        context_ok = current >= settings.local_context_tokens
        if not missing and context_ok and "ollama" not in self.redo:
            self.p.say(
                f"✓ Local model: already done (models pulled, OLLAMA_CONTEXT_LENGTH={current})"
            )
            return
        for model in missing:
            if not self.p.confirm(f"Pull the Ollama model {model}?", True):
                continue
            code = self.system.run_interactive(["ollama", "pull", model])
            if code != 0:
                self.p.say(f"Pulling {model} failed (exit {code}).")
        if context_ok and "ollama" not in self.redo:
            return

        def check(text: str) -> str | None:
            return None if _positive_int(text) else "Enter a positive whole number."

        size = self._ask_valid(
            "Local context size in tokens", check, str(settings.local_context_tokens)
        )
        if size is None:
            return
        value = str(int(size))
        if self._write_env(
            {"PERSONALAI_LOCAL_CONTEXT_TOKENS": value, "OLLAMA_CONTEXT_LENGTH": value},
            "Save these context settings?",
        ):
            self.p.say("Quit Ollama from the tray and start it again so it picks up the value.")

    def _authorised(self, settings: Settings) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for account in settings.google_accounts:
            raw = self.keystore.get(token_secret_name(account))
            if raw is None:
                continue
            try:
                granted = granted_scopes(raw)
            except ValueError:
                granted = frozenset()
            found[account] = [s for s in SERVICE_SCOPES if frozenset(scopes_for([s])) <= granted]
        return found

    def google(self) -> None:
        self._header(5, "Google accounts")
        authorised = self._authorised(self._settings())
        for account, services in authorised.items():
            self.p.say(f"  {account}: {', '.join(services) or 'no services'}")
        if not self.p.confirm("Add or update a Google account?", not authorised):
            if authorised:
                self.p.say("✓ Google accounts: already done (at least one is authorised)")
            return
        used_client_file = False
        while True:
            account = self.p.ask("Google account address (blank to finish)").strip().lower()
            if not account:
                break
            if not _ADDRESS.fullmatch(account):
                self.p.say("That does not look like an email address.")
                continue
            chosen = self._ask_services()
            if chosen is None:
                continue
            path = ""
            if self.keystore.get(CLIENT_SECRET_NAME) is None:
                path = self._ask_client_path()
                if not path:
                    continue
                used_client_file = True
            if not self.p.confirm(
                f"Sign in {account} for {', '.join(chosen)} (opens your browser)?", True
            ):
                continue
            argv = [
                "uv",
                "run",
                "--directory",
                str(self.server_dir),
                "python",
                "scripts/setup_google_oauth.py",
                "--account",
                account,
                "--services",
                ",".join(chosen),
            ]
            if path:
                argv += ["--client-secret", path]
            code = self.system.run_interactive(argv)
            if code != 0:
                self.p.say(f"Google sign-in failed (exit {code}).")
                continue
            self._merge_accounts(account, chosen)
        if used_client_file:
            self.p.say("Delete the downloaded client JSON file now; it is stored in the keyring.")

    def _ask_services(self) -> list[str] | None:
        def check(text: str) -> str | None:
            chosen = _split(text.lower())
            if not chosen:
                return "Name at least one service."
            bad = [s for s in chosen if s not in SERVICE_SCOPES]
            return f"Unknown: {', '.join(bad)}" if bad else None

        answer = self._ask_valid(
            f"Services ({', '.join(SERVICE_SCOPES)}; comma-separated)", check, "gmail"
        )
        return None if answer is None else list(dict.fromkeys(_split(answer.lower())))

    def _ask_client_path(self) -> str:
        def check(text: str) -> str | None:
            return None if text and Path(text).is_file() else "That file does not exist."

        answer = self._ask_valid("Path to the downloaded OAuth client JSON", check)
        return (answer or "").strip().strip('"')

    def _merge_accounts(self, account: str, services: Sequence[str]) -> None:
        changes: dict[str, str] = {}
        for service in services:
            name = _ACCOUNT_ENV[service]
            existing = [a.lower() for a in _split(self._env_value(name) or "")]
            merged = list(dict.fromkeys([*existing, account]))
            if merged != existing:
                changes[name] = ",".join(merged)
        if changes:
            self._write_env(changes, f"Use {account} for these connectors?")

    def profile(self) -> None:
        self._header(6, "Your profile")
        settings = self._settings()
        if settings.owner_emails and "profile" not in self.redo:
            self.p.say("✓ Profile: already done (PERSONALAI_OWNER_EMAILS is set)")
            return
        owners = self.p.ask(
            "Your email addresses (comma-separated)", ",".join(settings.google_accounts)
        )
        if not _split(owners):
            self.p.say("No address given; skipping this step.")
            return
        values = {"PERSONALAI_OWNER_EMAILS": ",".join(_split(owners))}
        vips = self.p.ask("VIP senders (comma-separated, optional)")
        domains = self.p.ask("College domains (comma-separated, optional)")
        roots = self.p.ask("Folders the agent may read (separated by ;, optional)")
        if _split(vips):
            values["PERSONALAI_VIP_SENDERS"] = ",".join(_split(vips))
        if _split(domains):
            values["PERSONALAI_COLLEGE_DOMAINS"] = ",".join(_split(domains))
        if _split(roots, ";"):
            values["PERSONALAI_FILE_ROOTS"] = ";".join(_split(roots, ";"))
        self._write_env(values, "Save your profile?")

    def network(self) -> None:
        self._header(7, "Network")
        addresses = probes.tailscale_ipv4(self.system)
        if not addresses:
            self.p.say("No Tailscale address found. Install Tailscale, sign in, then run setup")
            self.p.say("again. Skipping this step.")
            return
        value = f"127.0.0.1,{addresses[0]}"
        try:
            validate_bind_hosts(_split(value))
        except UnsafeBindAddress as exc:
            self.p.say(f"Refusing to bind to {value}: {exc}")
            return
        if self._env_value("PERSONALAI_BIND_HOSTS") == value and "network" not in self.redo:
            self.p.say(f"✓ Network: already done (PERSONALAI_BIND_HOSTS={value})")
            return
        self._write_env({"PERSONALAI_BIND_HOSTS": value}, "Bind the server to these addresses?")

    def task(self) -> None:
        self._header(8, "Background task")
        before = probes.scheduled_task(self.system)
        was_running = before.exists and before.status == "Running"
        written_before = bool(self.written)
        if before.exists and "task" not in self.redo:
            self.p.say(
                f"✓ Background task: already installed ({before.status or 'status unknown'})"
            )
        else:
            if not self.p.confirm(f"Install the '{probes.TASK_NAME}' scheduled task?", True):
                return
            script = self.server_dir / "scripts" / "install_task.ps1"
            code = self._powershell(["-File", str(script)], bypass=True)
            if code != 0:
                self.p.say(f"Installing the task failed (exit {code}).")
                return
        state = probes.scheduled_task(self.system)
        if state.status != "Running":
            if self.p.confirm("Start the task now?", True):
                self._start_task()
        elif (
            was_running
            and written_before
            and self.p.confirm(
                "Settings changed during setup; restart the task so it picks them up?", True
            )
        ):
            self._powershell(["-Command", f"Stop-ScheduledTask -TaskName '{probes.TASK_NAME}'"])
            self._start_task()

    def _powershell(self, args: Sequence[str], *, bypass: bool = False) -> int:
        argv = ["powershell", "-NoProfile"]
        if bypass:
            argv += ["-ExecutionPolicy", "Bypass"]
        return self.system.run_interactive([*argv, *args])

    def _start_task(self) -> None:
        code = self._powershell(["-Command", f"Start-ScheduledTask -TaskName '{probes.TASK_NAME}'"])
        if code != 0:
            self.p.say(f"Starting the task failed (exit {code}).")

    def power(self) -> None:
        self._header(9, "Power settings")
        settings = probes.power_settings(self.system)
        if settings.ok and "power" not in self.redo:
            self.p.say("✓ Power settings: already done (no sleep or hibernate on AC)")
            return
        self.p.say(
            f"  On AC: standby={_seconds(settings.standby_ac)}, "
            f"hibernate={_seconds(settings.hibernate_ac)}, lid action={_lid(settings.lid_ac)}"
        )
        self.p.say("The laptop must stay awake on AC. Setup never changes power settings.")
        self.p.say("Run these in your own PowerShell:")
        for command in probes.POWER_FIX_COMMANDS:
            self.p.say(f"  {command}")
        self.p.ask("Press Enter when done")
        if probes.power_settings(self.system).ok:
            self.p.say("Power settings now look right.")
        else:
            self.p.say("Power settings still differ; fix them later (setup can be run again).")

    def pair(self) -> None:
        self._header(10, "Phone pairing")
        db_path = self._settings().db_path
        if not db_path.exists():
            self.p.say("The server has not started yet (no database). Start it, then run setup")
            self.p.say("again to pair the phone. Skipping this step.")
            return
        count = _active_devices(db_path)
        if count is None:
            self.p.say("Could not read the device list; skipping this step.")
            return
        if count > 0 and "pair" not in self.redo:
            self.p.say(f"✓ Phone pairing: already done ({count} paired device(s))")
            return
        if not self.p.confirm("Open a pairing window now?", True):
            return
        self.open_pairing()
        self.p.ask("Press Enter after pairing on the phone")
        after = _active_devices(db_path)
        if after:
            self.p.say("Phone paired.")
        else:
            self.p.say("No paired device yet; run setup again to retry.")

    def run(self) -> int:
        self.prereqs()
        self.nvidia_key()
        self.models()
        self.ollama()
        self.google()
        self.profile()
        self.network()
        self.task()
        self.power()
        self.pair()
        self.p.say("Running agent doctor")
        code = self.run_doctor()
        self.p.say("Setup finished." if code == 0 else "Setup finished; doctor found problems.")
        return code


def _seconds(value: int | None) -> str:
    if value is None:
        return "unknown"
    return "never" if value == 0 else f"{value}s"


def _lid(value: int | None) -> str:
    names = {0: "do nothing", 1: "sleep", 2: "hibernate", 3: "shut down"}
    return "unknown" if value is None else names.get(value, str(value))


def _active_devices(db_path: Path) -> int | None:
    """Non-revoked paired devices, or ``None`` if the database cannot be read."""
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute("SELECT COUNT(*) FROM devices WHERE revoked = 0").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0])


def run_setup(
    system: System,
    prompter: Prompter,
    keystore: KeyStore,
    *,
    server_dir: Path,
    run_doctor: Callable[[], int],
    open_pairing: Callable[[], None],
    redo: Sequence[str] = (),
) -> int:
    """Run the wizard. 0 when finished (the doctor's exit code), 2 if refused, 1 if stopped."""
    if system.platform != "win32":
        prompter.say("Setup is for the Windows laptop. On other systems follow the appendix in")
        prompter.say("docs/SETUP.md by hand.")
        return 2
    unknown = [step for step in redo if step not in STEP_IDS]
    if unknown:
        prompter.say(f"Unknown step(s): {', '.join(unknown)}. Valid: {', '.join(STEP_IDS)}.")
        return 2
    wizard = _Wizard(
        system, prompter, keystore, server_dir, run_doctor, open_pairing, frozenset(redo)
    )
    try:
        return wizard.run()
    except _Stop as stop:
        return stop.code
    except (EOFError, KeyboardInterrupt):
        prompter.say("Setup stopped; run it again to continue.")
        return 1
