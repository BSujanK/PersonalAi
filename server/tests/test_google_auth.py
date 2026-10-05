from __future__ import annotations

import json

import pytest

from agent.connectors.google_auth import (
    CALENDAR_EVENTS,
    CLASSROOM_ANNOUNCEMENTS,
    CLASSROOM_COURSES,
    CLASSROOM_COURSEWORK,
    CLASSROOM_MATERIALS,
    CLIENT_SECRET_NAME,
    DRIVE_FILE,
    DRIVE_READONLY,
    GMAIL_MODIFY,
    IDENTITY_SCOPES,
    SERVICE_SCOPES,
    GoogleAuth,
    GoogleNotConfigured,
    granted_scopes,
    merged_scopes,
    scopes_for,
    token_secret_name,
)
from agent.store.keystore import KeyStore
from tests.conftest import SizeLimitedKeyring

ACCOUNT = "me@example.com"


def _store(scopes: list[str] | str) -> KeyStore:
    keystore = KeyStore()
    keystore.set(
        CLIENT_SECRET_NAME,
        json.dumps({"installed": {"client_id": "cid", "client_secret": "csec"}}),
    )
    keystore.set(
        token_secret_name(ACCOUNT),
        json.dumps({"refresh_token": "rt", "token": "at", "scopes": scopes}),
    )
    return keystore


def test_missing_client_and_token_raise() -> None:
    with pytest.raises(GoogleNotConfigured):
        GoogleAuth(KeyStore()).credentials(ACCOUNT, [GMAIL_MODIFY])
    keystore = KeyStore()
    keystore.set(CLIENT_SECRET_NAME, json.dumps({"installed": {"client_id": "cid"}}))
    with pytest.raises(GoogleNotConfigured):
        GoogleAuth(keystore).credentials(ACCOUNT, [GMAIL_MODIFY])


def test_token_with_only_gmail_scope_serves_gmail_not_calendar() -> None:
    auth = GoogleAuth(_store([GMAIL_MODIFY]))
    creds = auth.credentials(ACCOUNT, [GMAIL_MODIFY])
    assert creds.client_id == "cid"
    assert creds.refresh_token == "rt"
    with pytest.raises(GoogleNotConfigured):
        auth.credentials(ACCOUNT, [CALENDAR_EVENTS])


def test_same_credentials_object_shared_across_services() -> None:
    auth = GoogleAuth(_store([GMAIL_MODIFY, CALENDAR_EVENTS]))
    assert auth.credentials(ACCOUNT, [GMAIL_MODIFY]) is auth.credentials(ACCOUNT, [CALENDAR_EVENTS])


def test_persist_hook_writes_only_when_token_changed() -> None:
    keystore = _store([GMAIL_MODIFY])
    auth = GoogleAuth(keystore)
    creds = auth.credentials(ACCOUNT, [GMAIL_MODIFY])
    persist = auth.persist_hook(ACCOUNT)
    before = keystore.get(token_secret_name(ACCOUNT))
    persist()
    assert keystore.get(token_secret_name(ACCOUNT)) == before
    creds.token = "refreshed"
    persist()
    stored = keystore.get(token_secret_name(ACCOUNT))
    assert stored != before
    assert stored is not None
    assert json.loads(stored)["token"] == "refreshed"


def test_persist_hook_chunks_long_tokens(size_limited_keyring: SizeLimitedKeyring) -> None:
    keystore = _store([GMAIL_MODIFY])
    auth = GoogleAuth(keystore)
    creds = auth.credentials(ACCOUNT, [GMAIL_MODIFY])
    creds.token = "t" * 2000
    auth.persist_hook(ACCOUNT)()
    stored = keystore.get(token_secret_name(ACCOUNT))
    assert stored is not None
    assert json.loads(stored)["token"] == "t" * 2000
    assert any("#chunk:" in user for (_, user) in size_limited_keyring._store)


def test_scopes_for_rejects_unknown_service() -> None:
    with pytest.raises(ValueError):
        scopes_for(["gmail", "bogus"])


def test_scopes_for_is_stable_and_deduplicated() -> None:
    assert scopes_for(["drive", "gmail", "drive"]) == (DRIVE_READONLY, DRIVE_FILE, GMAIL_MODIFY)


def test_merged_scopes_keeps_previous_grants() -> None:
    existing = json.dumps({"scopes": [GMAIL_MODIFY]})
    merged = merged_scopes(existing, ["calendar"])
    assert set(merged) == {GMAIL_MODIFY, CALENDAR_EVENTS, *IDENTITY_SCOPES}
    assert merged == tuple(sorted(merged))


def test_merged_scopes_without_existing_token() -> None:
    assert set(merged_scopes(None, ["gmail"])) == {GMAIL_MODIFY, *IDENTITY_SCOPES}


@pytest.mark.parametrize(
    "raw", [[GMAIL_MODIFY, CALENDAR_EVENTS], f"{GMAIL_MODIFY} {CALENDAR_EVENTS}"]
)
def test_granted_scopes_accepts_list_or_string(raw: list[str] | str) -> None:
    assert granted_scopes(json.dumps({"scopes": raw})) == {GMAIL_MODIFY, CALENDAR_EVENTS}


def test_granted_scopes_none() -> None:
    assert granted_scopes(None) == frozenset()


# What Google actually returned for a real college account that requested coursework.me.readonly.
GRANTED_WITH_OLD_NAME = [
    CLASSROOM_COURSES,
    CLASSROOM_ANNOUNCEMENTS,
    CLASSROOM_MATERIALS,
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
]


def test_old_coursework_scope_name_counts_as_classroom_granted() -> None:
    granted = granted_scopes(json.dumps({"scopes": GRANTED_WITH_OLD_NAME}))
    assert set(SERVICE_SCOPES["classroom"]) <= granted
    creds = GoogleAuth(_store(GRANTED_WITH_OLD_NAME)).credentials(ACCOUNT, [CLASSROOM_COURSEWORK])
    assert creds.refresh_token == "rt"
