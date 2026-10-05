"""Command-line entry point: ``serve`` (default) and ``pair``."""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import segno
import uvicorn

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.connectors.gmail_google import build_gmail_api
from agent.connectors.google_auth import GoogleAuth
from agent.core.approvals import ApprovalEngine
from agent.core.audit import AuditLog
from agent.core.clock import utcnow
from agent.core.llm import build_default_client
from agent.core.netguard import UnsafeBindAddress, validate_bind_hosts
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.finance.services import FinanceServices, setup_finance
from agent.mail.classify import MailClassifier, build_classifier_llm
from agent.mail.services import MailServices, cached_api_factory
from agent.mail.store import MailStore
from agent.mail.sync import MailSync
from agent.mail.tools import register_mail_tools
from agent.scheduler import (
    DEADLINE_JOB_ID,
    FILE_INDEX_JOB_ID,
    FINANCE_CATEGORIZE_JOB_ID,
    MAIL_JOB_ID,
    Job,
    start_jobs,
)
from agent.store.backup import BackupError, create_backup, restore_backup
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.devices import list_devices, revoke_devices
from agent.store.keystore import InsecureKeyringError, KeyStore, assert_secure_backend
from agent.workspace.services import WorkspaceServices, deadline_proposer, setup_workspace

EXIT_REFUSED = 2


def _refuse(message: str) -> int:
    print(f"refused: {message}", file=sys.stderr)
    return EXIT_REFUSED


def _setup_mail(
    settings: Settings,
    db: Database,
    db_key: bytes,
    google_auth: GoogleAuth,
    registry: ToolRegistry,
    finance: FinanceServices,
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
        on_new=finance.ingest.ingest_email,
    )
    register_mail_tools(registry, store, api_for, utcnow)
    return MailServices(store, sync, api_for)


def _background_jobs(
    settings: Settings,
    db: Database,
    approvals: ApprovalEngine,
    mail: MailServices | None,
    workspace: WorkspaceServices,
    finance: FinanceServices,
) -> list[Job]:
    jobs: list[Job] = []
    if mail is not None:
        sync = mail.sync
        jobs.append(
            Job(
                MAIL_JOB_ID,
                lambda: sync.sync_all(settings.mail_accounts),
                settings.mail_poll_minutes,
            )
        )
    proposer = deadline_proposer(settings, db, approvals, workspace, utcnow)
    if proposer is not None:
        jobs.append(Job(DEADLINE_JOB_ID, proposer.run, settings.deadline_poll_minutes))
    if workspace.file_index is not None:
        jobs.append(
            Job(FILE_INDEX_JOB_ID, workspace.file_index.refresh, settings.file_index_minutes)
        )
    jobs.append(
        Job(FINANCE_CATEGORIZE_JOB_ID, finance.categorizer.run, settings.finance_categorize_minutes)
    )
    return jobs


def _serve(settings: Settings) -> int:
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
        if settings.mail_accounts:
            mail = _setup_mail(settings, db, db_key, google_auth, registry, finance)
        workspace = setup_workspace(settings, db, db_key, registry, google_auth, utcnow)
    except (InsecureKeyringError, UnsafeBindAddress, ValueError) as exc:
        return _refuse(str(exc))
    app = create_app(
        settings, db=db, keystore=keystore, llm=llm, registry=registry, mail=mail, finance=finance
    )
    scheduler = start_jobs(
        _background_jobs(settings, db, app.state.approvals, mail, workspace, finance)
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
            )
        )
        for host in hosts
    ]
    threads = [threading.Thread(target=s.run, daemon=True) for s in servers[1:]]
    for thread in threads:
        thread.start()
    try:
        servers[0].run()
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=5)
    return 0


_TAILSCALE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


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


def main(
    argv: Sequence[str] | None = None,
    *,
    read_passphrase: Callable[[str], str] = getpass.getpass,
) -> int:
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
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        return _refuse(f"invalid configuration: {exc}")
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
