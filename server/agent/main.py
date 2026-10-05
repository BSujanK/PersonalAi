"""Command-line entry point: ``serve`` (default) and ``pair``."""

from __future__ import annotations

import argparse
import sys
import threading
from collections.abc import Sequence

import uvicorn

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.connectors.gmail_google import build_gmail_api
from agent.connectors.google_auth import GoogleAuth
from agent.core.approvals import ApprovalEngine
from agent.core.clock import utcnow
from agent.core.llm import build_default_client
from agent.core.netguard import UnsafeBindAddress, validate_bind_hosts
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.mail.classify import MailClassifier, build_classifier_llm
from agent.mail.services import MailServices, cached_api_factory
from agent.mail.store import MailStore
from agent.mail.sync import MailSync
from agent.mail.tools import register_mail_tools
from agent.scheduler import DEADLINE_JOB_ID, FILE_INDEX_JOB_ID, MAIL_JOB_ID, Job, start_jobs
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import InsecureKeyringError, KeyStore, assert_secure_backend
from agent.workspace.services import WorkspaceServices, deadline_proposer, setup_workspace

EXIT_REFUSED = 2


def _refuse(message: str) -> int:
    print(f"refusing to start: {message}", file=sys.stderr)
    return EXIT_REFUSED


def _setup_mail(
    settings: Settings,
    db: Database,
    db_key: bytes,
    google_auth: GoogleAuth,
    registry: ToolRegistry,
) -> MailServices:
    store = MailStore(db, FieldCipher(db_key), db_key)
    api_for = cached_api_factory(
        settings.mail_accounts, lambda account: build_gmail_api(account, google_auth)
    )
    classifier = MailClassifier(
        store, build_classifier_llm(settings), Redactor(settings.redaction_emails), settings
    )
    sync = MailSync(store, api_for, classifier, utcnow, settings.mail_initial_days)
    register_mail_tools(registry, store, api_for, utcnow)
    return MailServices(store, sync, api_for)


def _background_jobs(
    settings: Settings,
    db: Database,
    approvals: ApprovalEngine,
    mail: MailServices | None,
    workspace: WorkspaceServices,
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
        if settings.mail_accounts:
            mail = _setup_mail(settings, db, db_key, google_auth, registry)
        workspace = setup_workspace(settings, db, db_key, registry, google_auth, utcnow)
    except (InsecureKeyringError, UnsafeBindAddress, ValueError) as exc:
        return _refuse(str(exc))
    app = create_app(settings, db=db, keystore=keystore, llm=llm, registry=registry, mail=mail)
    scheduler = start_jobs(_background_jobs(settings, db, app.state.approvals, mail, workspace))
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


def _pair(settings: Settings) -> int:
    try:
        assert_secure_backend()
        hosts = validate_bind_hosts(settings.bind_hosts)
    except (InsecureKeyringError, UnsafeBindAddress) as exc:
        return _refuse(str(exc))
    db = Database(settings.db_path)
    code = open_pairing_window(db, utcnow, settings.pairing_window_seconds)
    print(f"Pairing code: {code}")
    print(f"Valid for {settings.pairing_window_seconds} seconds, single use.")
    host = f"[{hosts[0]}]" if hosts[0].version == 6 else str(hosts[0])
    print(f"Pair at: http://{host}:{settings.port}/pair")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the server (default)")
    sub.add_parser("pair", help="open a pairing window and print the code")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        return _refuse(f"invalid configuration: {exc}")
    if args.command == "pair":
        return _pair(settings)
    return _serve(settings)
