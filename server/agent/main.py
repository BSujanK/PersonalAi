"""Command-line entry point: ``serve`` (default), ``pair``, ``restart``, ``doctor`` and more."""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import logging
import logging.handlers
import socket
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import segno
import uvicorn

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.api.today_cache import TodayCache
from agent.config import Settings
from agent.connectors.accounts import cached_factory
from agent.connectors.gcal import OwnCalendarApi
from agent.connectors.gcal_google import build_own_calendar_api
from agent.connectors.gmail import MailMessage
from agent.connectors.gmail_google import build_gmail_api
from agent.connectors.google_auth import GoogleAuth
from agent.core.audit import AuditLog
from agent.core.clock import utcnow
from agent.core.llm import build_default_client
from agent.core.netguard import UnsafeBindAddress, validate_bind_hosts
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.finance.services import FinanceServices, setup_finance
from agent.golive.doctor import run_doctor
from agent.golive.probes import TASK_NAME
from agent.golive.service import restart_server
from agent.golive.setup import STEP_IDS, ConsolePrompter, run_setup
from agent.golive.supervisor import server_command, supervise
from agent.golive.system import RealSystem
from agent.mail.classify import MailClassifier, build_classifier_llm
from agent.mail.services import MailServices, cached_api_factory
from agent.mail.store import MailStore
from agent.mail.sync import MailSync, sync_and_record
from agent.mail.tools import register_mail_tools
from agent.news.feeds import NewsFeeds
from agent.news.tools import register_news_tool
from agent.news.topics import parse_news_topics
from agent.outbound.services import register_outbound_tools
from agent.proactive.alerts import AlertStore
from agent.proactive.autocal import AutoCalendar
from agent.proactive.deadlines import DeadlineStore
from agent.proactive.recheck import apply_rejections, find_rejected
from agent.proactive.services import Fanout, ProactiveServices, setup_proactive
from agent.scheduler import (
    ALERT_JOB_ID,
    CLASSROOM_DEADLINE_JOB_ID,
    FILE_INDEX_JOB_ID,
    FINANCE_CATEGORIZE_JOB_ID,
    MAIL_DEADLINE_JOB_ID,
    MAIL_DEADLINE_SCAN_DELAY_SECONDS,
    MAIL_DEADLINE_SCAN_MINUTES,
    MAIL_JOB_ID,
    TODAY_JOB_ID,
    Job,
    start_jobs,
)
from agent.store.backup import BackupError, create_backup, restore_backup
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.devices import list_devices, revoke_devices
from agent.store.keystore import InsecureKeyringError, KeyStore, assert_secure_backend
from agent.web.tools import register_web_tools
from agent.workspace.services import WorkspaceServices, setup_workspace

EXIT_REFUSED = 2
SERVER_DIR = Path(__file__).resolve().parents[1]


def _refuse(message: str) -> int:
    if sys.stderr is not None:  # None under pythonw
        print(f"refused: {message}", file=sys.stderr)
    return EXIT_REFUSED


@dataclass(frozen=True)
class _MailHooks:
    """What runs around mail sync. Filled in as the services that listen are built."""

    on_new: Fanout[[MailMessage]]
    pass_start: Fanout[[]]
    pass_end: Fanout[[]]


def _setup_mail(
    settings: Settings,
    db: Database,
    db_key: bytes,
    google_auth: GoogleAuth,
    registry: ToolRegistry,
    hooks: _MailHooks,
) -> MailServices:
    store = MailStore(db, FieldCipher(db_key), db_key)
    api_for = cached_api_factory(
        settings.mail_accounts, lambda account: build_gmail_api(account, google_auth)
    )
    classifier = MailClassifier(
        store, build_classifier_llm(settings), Redactor(settings.redaction_emails), settings
    )
    sync = MailSync(
        store,
        api_for,
        classifier,
        utcnow,
        settings.mail_initial_days,
        on_new=hooks.on_new,
        on_pass_start=hooks.pass_start,
        on_pass_end=hooks.pass_end,
    )
    register_mail_tools(registry, store, api_for, utcnow)
    return MailServices(store, sync, api_for)


def _setup_proactive(
    settings: Settings,
    db: Database,
    db_key: bytes,
    google_auth: GoogleAuth,
    registry: ToolRegistry,
    mail: MailServices | None,
    workspace: WorkspaceServices,
    hooks: _MailHooks,
) -> ProactiveServices:
    own_calendar_api_for: Callable[[str], OwnCalendarApi] | None = None
    if settings.calendar_accounts:
        own_calendar_api_for = cached_factory(
            settings.calendar_accounts, lambda account: build_own_calendar_api(account, google_auth)
        )
    proactive = setup_proactive(
        settings,
        db,
        db_key,
        registry,
        utcnow,
        mail_store=mail.store if mail is not None else None,
        classifier_llm=build_classifier_llm(settings),
        classroom_api_for=workspace.classroom_api_for,
        own_calendar_api_for=own_calendar_api_for,
    )
    hooks.on_new.add(proactive.deadlines.on_new_mail)
    if proactive.mail_alerts is not None:
        hooks.on_new.add(proactive.mail_alerts.on_new_mail)
        hooks.pass_start.add(proactive.mail_alerts.begin_pass)
        hooks.pass_end.add(proactive.mail_alerts.end_pass)
    if settings.news_feeds:
        news_topics = parse_news_topics(settings.news_topics)
        register_news_tool(registry, NewsFeeds(settings.news_feeds, topics=news_topics))
    return proactive


def _background_jobs(
    settings: Settings,
    db: Database,
    mail: MailServices | None,
    workspace: WorkspaceServices,
    finance: FinanceServices,
    proactive: ProactiveServices,
    today: TodayCache,
) -> list[Job]:
    jobs: list[Job] = []
    if mail is not None:
        sync = mail.sync
        jobs.append(
            Job(
                MAIL_JOB_ID,
                lambda: sync_and_record(sync, db, settings.mail_accounts),
                settings.mail_poll_minutes,
            )
        )
    if workspace.classroom_api_for is not None:
        jobs.append(
            Job(
                CLASSROOM_DEADLINE_JOB_ID,
                proactive.deadlines.scan_classroom,
                settings.deadline_poll_minutes,
            )
        )
    if mail is not None:
        # A catch-up over stored mail (see DeadlineCollector.scan_stored_mail): once shortly after
        # startup, so it never delays the first mail sync, then daily.
        jobs.append(
            Job(
                MAIL_DEADLINE_JOB_ID,
                proactive.deadlines.scan_stored_mail,
                MAIL_DEADLINE_SCAN_MINUTES,
                start_delay_seconds=MAIL_DEADLINE_SCAN_DELAY_SECONDS,
            )
        )
    if workspace.file_index is not None:
        jobs.append(
            Job(FILE_INDEX_JOB_ID, workspace.file_index.refresh, settings.file_index_minutes)
        )
    jobs.append(
        Job(FINANCE_CATEGORIZE_JOB_ID, finance.categorizer.run, settings.finance_categorize_minutes)
    )
    jobs.append(Job(ALERT_JOB_ID, proactive.alert_job.run, settings.alert_poll_minutes))
    jobs.append(Job(TODAY_JOB_ID, today.refresh, settings.today_refresh_minutes))
    return jobs


def _log_path(settings: Settings) -> Path:
    return settings.db_path.parent / "agent.log"


def _configure_logging(settings: Settings) -> None:
    """INFO for the agent's own loggers (counts and routes only, never content).

    Goes to stderr (when there is one: ``pythonw`` has none) and to a rotating ``agent.log`` next
    to the database, which is what a console-less scheduled task leaves to debug with.
    """
    logger = logging.getLogger("agent")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    log_path = _log_path(settings)
    wanted: list[logging.Handler] = []
    if sys.stderr is not None and not any(
        type(h) is logging.StreamHandler for h in logger.handlers
    ):
        wanted.append(logging.StreamHandler())
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and Path(h.baseFilename) == log_path.absolute()
        for h in logger.handlers
    ):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        wanted.append(
            logging.handlers.RotatingFileHandler(
                log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True
            )
        )
    for handler in wanted:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    _log_uvicorn_errors(logger)


class _NoTraceback(logging.Filter):
    """Keeps a traceback (whose frames and values can carry content) out of the log: the record
    is written without it and the message ends with the exception type instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[0] is not None:
            record.msg = f"{record.getMessage()} ({record.exc_info[0].__name__})"
            record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def _log_uvicorn_errors(agent_logger: logging.Logger) -> None:
    """Send uvicorn's own warnings and errors (e.g. a crashed request) to the agent's handlers.

    uvicorn is started with ``log_config=None``: its default config would replace these handlers.
    """
    uvicorn_logger = logging.getLogger("uvicorn.error")
    for handler in agent_logger.handlers:
        if handler not in uvicorn_logger.handlers:
            uvicorn_logger.addHandler(handler)
    if not any(isinstance(f, _NoTraceback) for f in uvicorn_logger.filters):
        uvicorn_logger.addFilter(_NoTraceback())
    uvicorn_logger.setLevel(logging.WARNING)
    uvicorn_logger.propagate = False  # the handlers above already write it


def _supervise(settings: Settings) -> int:
    if sys.platform != "win32":
        if sys.stderr is not None:
            print(
                "supervise is only available on Windows (it needs a job object).", file=sys.stderr
            )
        return 1
    return supervise(server_command(), SERVER_DIR, _log_path(settings))


def _serve(settings: Settings) -> int:
    _configure_logging(settings)
    try:
        return _run_server(settings)
    except Exception as exc:
        logging.getLogger("agent").error("server crashed: %s", type(exc).__name__)
        raise


def _run_server(settings: Settings) -> int:
    registry = ToolRegistry()
    mail: MailServices | None = None
    try:
        assert_secure_backend()
        hosts = validate_bind_hosts(settings.bind_hosts)
        db = Database(settings.db_path)
        keystore = KeyStore()
        llm = build_default_client(settings, keystore)
        db_key = keystore.get_or_create_bytes("db_key")
        google_auth = GoogleAuth(keystore)
        finance = setup_finance(settings, db, db_key, registry, utcnow)
        hooks = _MailHooks(Fanout(), Fanout(), Fanout())
        hooks.on_new.add(finance.ingest.ingest_email)
        if settings.mail_accounts:
            mail = _setup_mail(settings, db, db_key, google_auth, registry, hooks)
        workspace = setup_workspace(settings, db, db_key, registry, google_auth, utcnow)
        proactive = _setup_proactive(
            settings, db, db_key, google_auth, registry, mail, workspace, hooks
        )
        if settings.web_tools:
            register_web_tools(registry, settings, keystore)
        register_outbound_tools(
            registry, settings, mail, workspace.drive_api_for, workspace.file_roots
        )
    except (InsecureKeyringError, UnsafeBindAddress, ValueError) as exc:
        logging.getLogger("agent").error("server refused to start: %s", type(exc).__name__)
        return _refuse(str(exc))
    missing = wait_for_bind_addresses(hosts)
    if missing:
        # At logon Tailscale may not have its address yet. Exit non-zero so the supervisor
        # restarts the server with back-off instead of serving without the phone's listener.
        logging.getLogger("agent").error(
            "server refused to start: %d bind address(es) not available", len(missing)
        )
        return EXIT_BIND_UNAVAILABLE
    logging.getLogger("agent").info("server starting: hosts=%d port=%d", len(hosts), settings.port)
    app = create_app(
        settings,
        db=db,
        keystore=keystore,
        llm=llm,
        registry=registry,
        mail=mail,
        finance=finance,
        proactive=proactive,
    )
    today: TodayCache = app.state.today
    if mail is not None:
        hooks.pass_end.add(today.refresh_mail)  # new mail shows on /today without waiting
    scheduler = start_jobs(
        _background_jobs(settings, db, mail, workspace, finance, proactive, today)
    )
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                app,
                host=str(host),
                port=settings.port,
                server_header=False,
                proxy_headers=False,
                access_log=False,
                log_level="warning",
                log_config=None,
            )
        )
        for host in hosts
    ]
    # Every listener runs in its own thread; if any of them stops (for example it could not
    # bind), the whole server exits non-zero so the supervisor restarts it, rather than
    # silently serving on fewer addresses (the phone's Tailscale listener once died at logon).
    errors: list[BaseException] = []

    def listen(server: uvicorn.Server) -> None:
        try:
            server.run()
        except BaseException as exc:  # re-raised on the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=listen, args=(s,), daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    code = 0
    try:
        while all(thread.is_alive() for thread in threads):
            time.sleep(0.2)
        if errors:
            raise errors[0]
        if not all(server.started for server in servers):
            logging.getLogger("agent").error("a listener could not start; exiting")
            code = EXIT_BIND_UNAVAILABLE
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=5)
    return code


_TAILSCALE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
EXIT_BIND_UNAVAILABLE = 3
BIND_WAIT_SECONDS = 180.0
BIND_POLL_SECONDS = 5.0


def _bindable(host: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when this machine currently owns ``host`` (an ephemeral-port bind succeeds)."""
    family = socket.AF_INET6 if host.version == 6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((str(host), 0))
        except OSError:
            return False
    return True


def wait_for_bind_addresses(
    hosts: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
    *,
    timeout: float = BIND_WAIT_SECONDS,
    poll: float = BIND_POLL_SECONDS,
    bindable: Callable[[ipaddress.IPv4Address | ipaddress.IPv6Address], bool] = _bindable,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Wait until every bind address exists on this machine; return the ones still missing."""
    deadline = clock() + timeout
    while True:
        missing = [host for host in hosts if not bindable(host)]
        if not missing or clock() >= deadline:
            return missing
        logging.getLogger("agent").info("waiting for %d bind address(es) to come up", len(missing))
        sleep(poll)


def _phone_url(
    settings: Settings, hosts: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address]
) -> str | None:
    """The first Tailscale bind address: the only kind of address the phone app accepts."""
    for host in hosts:
        if any(host in net for net in _TAILSCALE):
            shown = f"[{host}]" if host.version == 6 else str(host)
            return f"http://{shown}:{settings.port}"
    return None


def _pair(settings: Settings, url: str | None) -> int:
    try:
        assert_secure_backend()
        hosts = validate_bind_hosts(settings.bind_hosts)
    except (InsecureKeyringError, UnsafeBindAddress) as exc:
        return _refuse(str(exc))
    phone_url = url.rstrip("/") if url else _phone_url(settings, hosts)
    db = Database(settings.db_path)
    code = open_pairing_window(db, utcnow, settings.pairing_window_seconds)
    if phone_url is None:
        print(
            "No Tailscale bind address is configured (PERSONALAI_BIND_HOSTS), so the phone "
            "cannot reach this server. Pass --url http://100.x.y.z:PORT (Tailscale IP) or "
            "enter the code by hand."
        )
    else:
        payload = json.dumps({"v": 1, "url": phone_url, "code": code}, separators=(",", ":"))
        print("Scan this with the PersonalAi app (Settings > Pair):")
        segno.make(payload, error="m").terminal(compact=True)
        print(f"Server: {phone_url}")
    active = [d for d in list_devices(db) if not d["revoked"]]
    if active:
        print(
            f"{len(active)} device(s) already paired. After pairing, remove old phones with "
            "`agent devices` and `agent revoke --device ID`."
        )
    print(f"Pairing code: {code}")
    print(f"Valid for {settings.pairing_window_seconds} seconds, single use.")
    return 0


def _devices(settings: Settings) -> int:
    db = Database(settings.db_path)
    devices = list_devices(db)
    if not devices:
        print("No paired devices.")
    for d in devices:
        state = "revoked" if d["revoked"] else "active"
        print(f"{d['id']}  {state:7}  {d['created_at']}  {d['name']}")
    return 0


def _revoke(settings: Settings, device_ids: list[str], revoke_all: bool) -> int:
    try:
        assert_secure_backend()
    except InsecureKeyringError as exc:
        return _refuse(str(exc))
    db = Database(settings.db_path)
    if revoke_all:
        device_ids = [d["id"] for d in list_devices(db) if not d["revoked"]]
    done = revoke_devices(db, KeyStore(), AuditLog(db, utcnow), device_ids)
    for device_id in done:
        print(f"Revoked {device_id}")
    missing = sorted(set(device_ids) - set(done))
    for device_id in missing:
        print(f"Not an active device: {device_id}", file=sys.stderr)
    return 1 if missing else 0


def _backup(settings: Settings, out_path: Path, read_passphrase: Callable[[str], str]) -> int:
    try:
        assert_secure_backend()
        passphrase = read_passphrase("Backup passphrase: ")
        if read_passphrase("Repeat passphrase: ") != passphrase:
            return _refuse("passphrases do not match")
        created_at = utcnow()
        create_backup(settings.db_path, out_path, passphrase, KeyStore(), lambda: created_at)
    except (InsecureKeyringError, BackupError) as exc:
        return _refuse(str(exc))
    print(f"Backup written: {out_path} ({out_path.stat().st_size} bytes)")
    print(f"Created at: {created_at.isoformat()}")
    return 0


def _restore(
    settings: Settings, in_path: Path, force: bool, read_passphrase: Callable[[str], str]
) -> int:
    try:
        assert_secure_backend()
        passphrase = read_passphrase("Backup passphrase: ")
        restore_backup(in_path, settings.db_path, passphrase, KeyStore(), force=force)
    except (InsecureKeyringError, BackupError) as exc:
        return _refuse(str(exc))
    print(f"Restored database: {settings.db_path}")
    print("Re-pair the phone (pair) and re-authorise Google and the NVIDIA key before serving.")
    return 0


def _doctor(settings: Settings, as_json: bool) -> int:
    return run_doctor(
        settings, RealSystem(), KeyStore(), as_json=as_json, out=sys.stdout, clock=utcnow
    )


def _restart(settings: Settings, task_name: str) -> int:
    return restart_server(RealSystem(), sys.stdout, settings=settings, task_name=task_name)


def _setup(redo: list[str]) -> int:
    try:
        assert_secure_backend()
    except InsecureKeyringError as exc:
        return _refuse(str(exc))

    def fresh_settings() -> Settings:
        return Settings.from_env()  # the wizard updates this process's environment as it goes

    def open_pairing() -> None:
        _pair(fresh_settings(), None)

    return run_setup(
        RealSystem(),
        ConsolePrompter(),
        KeyStore(),
        server_dir=SERVER_DIR,
        run_doctor=lambda: _doctor(fresh_settings(), as_json=False),
        open_pairing=open_pairing,
        redo=redo,
    )


def _deadlines_recheck(settings: Settings, apply: bool, out: TextIO) -> int:
    """List mail deadlines the current rules reject; with ``apply``, undo or dismiss them."""
    if not settings.mail_accounts:
        print(
            "No mail accounts are configured (PERSONALAI_MAIL_ACCOUNTS): nothing to check.",
            file=out,
        )
        return 0
    try:
        assert_secure_backend()
    except InsecureKeyringError as exc:
        return _refuse(str(exc))
    db = Database(settings.db_path)
    db_key = KeyStore().get_or_create_bytes("db_key")
    cipher = FieldCipher(db_key)
    deadlines = DeadlineStore(db, cipher, utcnow)
    offset = settings.finance_utc_offset_minutes
    rejected = find_rejected(db, deadlines, MailStore(db, cipher, db_key), settings, offset)
    for item in rejected:
        print(
            f"{item.deadline_id}  {item.kind}  {item.due.isoformat()}  {item.account}  "
            f"{item.title}  on calendar: {'yes' if item.on_calendar else 'no'}  {item.reason}",
            file=out,
        )
    if not rejected:
        print("No wrongly found mail deadlines.", file=out)
        return 0
    if not apply:
        print("dry run: nothing changed; re-run with --apply", file=out)
        return 0
    google_auth = GoogleAuth(KeyStore())
    api_for = cached_factory(
        settings.calendar_accounts, lambda account: build_own_calendar_api(account, google_auth)
    )
    audit = AuditLog(db, utcnow)
    autocal = AutoCalendar(
        db,
        deadlines,
        api_for,
        settings.deadline_calendar,
        utcnow,
        audit,
        AlertStore(db, cipher, utcnow, settings.briefing_time),
        settings.calendar_auto_add,
        offset,
    )
    counts = apply_rejections(rejected, autocal, db, audit)
    print(
        f"undone {counts.undone}, dismissed {counts.dismissed}, "
        f"refused {counts.refused}, failed {counts.failed}",
        file=out,
    )
    return 0


def _news_check(settings: Settings, urls: Sequence[str], out: TextIO) -> int:
    """Fetch each feed (the configured ones, or ``urls``) and say whether it can be read."""
    wanted = list(urls) or list(settings.news_feeds)
    if not wanted:
        print("No feeds to check: set PERSONALAI_NEWS_FEEDS or pass URLs.", file=out)
        return 1
    feeds = NewsFeeds(wanted)
    failed = False
    for url in wanted:
        try:
            feed = feeds.fetch(url)
        except Exception as exc:  # a failing feed must not stop the others being checked
            failed = True
            print(f"FAIL {type(exc).__name__} {url}", file=out)
        else:
            print(f"OK  {len(feed.items)} items  {url}", file=out)
    return 1 if failed else 0


def _tolerate_any_output(*streams: TextIO | None) -> None:
    """Never crash on a character the console's code page lacks (e.g. ``✓`` or ``⟨PHONE_1⟩``).

    Windows redirects and old consoles use cp1252, where printing those raises
    UnicodeEncodeError. Unencodable characters are replaced with ``?`` instead.
    """
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(
    argv: Sequence[str] | None = None,
    *,
    read_passphrase: Callable[[str], str] = getpass.getpass,
) -> int:
    _tolerate_any_output(sys.stdout, sys.stderr)
    parser = argparse.ArgumentParser(prog="agent")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the server (default)")
    pair = sub.add_parser("pair", help="open a pairing window and print the code and QR")
    pair.add_argument("--url", help="server URL for the phone, e.g. http://100.x.y.z:8765")
    sub.add_parser("devices", help="list paired devices")
    revoke = sub.add_parser(
        "revoke", help="revoke paired devices: their token stops working and approval key is erased"
    )
    which = revoke.add_mutually_exclusive_group(required=True)
    which.add_argument("--device", action="append", default=[], help="device id (repeatable)")
    which.add_argument("--all", action="store_true", help="revoke every active device")
    backup = sub.add_parser(
        "backup", help="write an encrypted backup of the database and its encryption key"
    )
    backup.add_argument("--out", required=True, type=Path, help="new backup file to create")
    restore = sub.add_parser(
        "restore",
        help="restore a backup; STOP THE SERVER FIRST. Phone pairing and Google/NVIDIA "
        "credentials are not in the backup and must be set up again",
    )
    restore.add_argument("--in", dest="in_path", required=True, type=Path, help="backup file")
    restore.add_argument(
        "--force",
        action="store_true",
        help="replace an existing database (kept aside as .pre-restore-<timestamp>) and db_key",
    )
    doctor = sub.add_parser("doctor", help="check every go-live prerequisite (read-only)")
    doctor.add_argument("--json", action="store_true", help="print the results as JSON")
    setup = sub.add_parser(
        "setup", help="interactive go-live wizard (Windows); asks before every change"
    )
    setup.add_argument(
        "--redo", action="append", default=[], choices=STEP_IDS, help="re-run a step (repeatable)"
    )
    restart = sub.add_parser(
        "restart",
        help="stop every running server of this user, then start the scheduled task "
        "(run this after updating the code)",
    )
    restart.add_argument("--task", default=TASK_NAME, help=argparse.SUPPRESS)
    news = sub.add_parser(
        "news-check", help="fetch the configured news feeds (or the given URLs) and report"
    )
    news.add_argument("urls", nargs="*", help="https feed URLs; default: PERSONALAI_NEWS_FEEDS")
    recheck = sub.add_parser(
        "deadlines-recheck",
        help="find mail deadlines the newsletter filter now rejects (dry run unless --apply)",
    )
    recheck.add_argument(
        "--apply", action="store_true", help="remove their calendar events and dismiss them"
    )
    sub.add_parser(
        "supervise",
        help="run the server under a console-less supervisor (used by the scheduled task)",
    )
    args = parser.parse_args(argv)
    if args.command == "setup":
        return _setup(args.redo)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        return _refuse(f"invalid configuration: {exc}")
    if args.command == "restart":
        return _restart(settings, args.task)
    if args.command == "supervise":
        return _supervise(settings)
    if args.command == "doctor":
        return _doctor(settings, args.json)
    if args.command == "news-check":
        return _news_check(settings, args.urls, sys.stdout)
    if args.command == "deadlines-recheck":
        return _deadlines_recheck(settings, args.apply, sys.stdout)
    if args.command == "pair":
        return _pair(settings, args.url)
    if args.command == "devices":
        return _devices(settings)
    if args.command == "revoke":
        return _revoke(settings, args.device, args.all)
    if args.command == "backup":
        return _backup(settings, args.out, read_passphrase)
    if args.command == "restore":
        return _restore(settings, args.in_path, args.force, read_passphrase)
    return _serve(settings)
