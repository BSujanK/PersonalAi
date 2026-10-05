"""One-time interactive Google sign-in (M7, run on the laptop). Stores secrets in the keyring.

Usage: python scripts/setup_google_oauth.py CLIENT_SECRET.json
Prints only the authorised account address.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from agent.connectors.gmail_google import (
    CLIENT_SECRET_NAME,
    GMAIL_SCOPE,
    GoogleGmailApi,
    token_secret_name,
)
from agent.store.keystore import KeyStore, assert_secure_backend


def main(argv: list[str]) -> int:  # pragma: no cover - interactive
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_secret", type=Path, help="OAuth client JSON from Google Cloud")
    args = parser.parse_args(argv)
    assert_secure_backend()
    keystore = KeyStore()
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), scopes=[GMAIL_SCOPE])
    credentials = flow.run_local_server(host="127.0.0.1", port=0)
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    account = str(GoogleGmailApi(service).profile()["emailAddress"]).lower()
    keystore.set(CLIENT_SECRET_NAME, json.dumps(json.loads(args.client_secret.read_text())))
    keystore.set(token_secret_name(account), credentials.to_json())
    print(f"Authorised {account}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
