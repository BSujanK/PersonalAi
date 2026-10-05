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
from agent.core.clock import utcnow
from agent.core.llm import build_default_client
from agent.core.netguard import UnsafeBindAddress, validate_bind_hosts
from agent.core.tools import ToolRegistry
from agent.store.db import Database
from agent.store.keystore import InsecureKeyringError, KeyStore, assert_secure_backend

EXIT_REFUSED = 2


def _refuse(message: str) -> int:
    print(f"refusing to start: {message}", file=sys.stderr)
    return EXIT_REFUSED


def _serve(settings: Settings) -> int:
    try:
        assert_secure_backend()
        hosts = validate_bind_hosts(settings.bind_hosts)
        db = Database(settings.db_path)
        keystore = KeyStore()
        llm = build_default_client(settings, keystore)
    except (InsecureKeyringError, UnsafeBindAddress, ValueError) as exc:
        return _refuse(str(exc))
    app = create_app(settings, db=db, keystore=keystore, llm=llm, registry=ToolRegistry())
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
