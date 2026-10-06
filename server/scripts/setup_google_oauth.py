"""Interactive Google sign-in (M7, run on the laptop). Stores secrets only in the OS keyring.

Usage: python scripts/setup_google_oauth.py --account you@example.com
           [--services gmail,calendar,classroom,drive] [--client-secret CLIENT.json]

Scopes are added incrementally: services already authorised for the account are kept. Prints only
the account address and the service names authorised.

"drive" asks for full Drive access (``auth/drive``), which drive_share needs to share files the
agent did not create. Accounts authorised before that only have ``drive.file``: re-run once with
``--services drive`` (``agent doctor`` says so). Every Drive change is still an approved action.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from agent.connectors.google_auth import (
    CLIENT_SECRET_NAME,
    SERVICE_SCOPES,
    client_config,
    granted_scopes,
    merged_scopes,
    token_secret_name,
)
from agent.store.keystore import KeyStore, assert_secure_backend


def main(argv: list[str]) -> int:  # pragma: no cover - interactive
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True, help="Google account address to authorise")
    parser.add_argument(
        "--services",
        default="gmail",
        help=f"comma-separated services to add ({', '.join(SERVICE_SCOPES)}); default gmail",
    )
    parser.add_argument(
        "--client-secret", type=Path, help="OAuth client JSON; stored in the keyring if given"
    )
    args = parser.parse_args(argv)
    account = str(args.account).strip().lower()
    services = [s.strip() for s in str(args.services).split(",") if s.strip()]

    assert_secure_backend()
    keystore = KeyStore()
    if args.client_secret is not None:
        client_raw = json.dumps(json.loads(args.client_secret.read_text(encoding="utf-8-sig")))
    else:
        client_raw = keystore.get(CLIENT_SECRET_NAME)
    if client_raw is None:
        print("No OAuth client found: pass --client-secret CLIENT.json once.", file=sys.stderr)
        return 2
    try:
        scopes = merged_scopes(keystore.get(token_secret_name(account)), services)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if "drive" in services:
        print(
            "Drive asks for full access to your Drive so the agent can share files you pick. "
            "It still cannot change, share or upload anything without your approval on the phone."
        )
    # Google also returns previously granted scopes, which oauthlib would otherwise reject.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = InstalledAppFlow.from_client_config(
        {"installed": client_config(client_raw)}, scopes=list(scopes)
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        login_hint=account,
        include_granted_scopes="true",
        access_type="offline",
        prompt="consent",
    )
    userinfo = (
        build("oauth2", "v2", credentials=credentials, cache_discovery=False)
        .userinfo()
        .get()
        .execute()
    )
    signed_in = str(userinfo.get("email", "")).lower()
    if signed_in != account:
        print(f"Signed in as a different account than {account}; nothing stored.", file=sys.stderr)
        return 1

    token = json.loads(credentials.to_json())
    granted = getattr(credentials, "granted_scopes", None) or scopes
    token["scopes"] = sorted(set(granted))
    keystore.set(CLIENT_SECRET_NAME, client_raw)
    keystore.set(token_secret_name(account), json.dumps(token))
    authorised = [
        name
        for name, needed in SERVICE_SCOPES.items()
        if set(needed) <= granted_scopes(json.dumps(token))
    ]
    print(f"Authorised {account}: {', '.join(authorised) or 'no services'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
