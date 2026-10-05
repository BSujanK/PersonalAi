"""One Google OAuth credential per account, shared by every Google connector.

Each account has a single token in the keyring that covers every scope granted to it so far.
``scripts/setup_google_oauth.py`` adds scopes incrementally; connectors only check that the scopes
they need are among those granted.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from typing import Any

from google.oauth2.credentials import Credentials

from agent.store.keystore import KeyStore

CLIENT_SECRET_NAME = "google_oauth_client"  # noqa: S105 - keyring entry name

GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
CLASSROOM_COURSES = "https://www.googleapis.com/auth/classroom.courses.readonly"
CLASSROOM_COURSEWORK = "https://www.googleapis.com/auth/classroom.coursework.me.readonly"
CLASSROOM_ANNOUNCEMENTS = "https://www.googleapis.com/auth/classroom.announcements.readonly"
CLASSROOM_MATERIALS = "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
# Used only by the setup script to confirm which account signed in.
IDENTITY_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.email")

# Google sometimes reports a granted scope under an older name than the one requested: asking
# for classroom.coursework.me.readonly comes back as classroom.student-submissions.me.readonly
# (the same "course work and grades" permission). Map old names to the ones we check for.
_CLASSROOM_SUBMISSIONS_OLD = (
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly"
)
SCOPE_ALIASES: dict[str, str] = {_CLASSROOM_SUBMISSIONS_OLD: CLASSROOM_COURSEWORK}


def normalise_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """The scopes plus the current name of any aliased ones."""
    names = frozenset(scopes)
    return names | frozenset(SCOPE_ALIASES[s] for s in names if s in SCOPE_ALIASES)


SERVICE_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": (GMAIL_MODIFY,),
    "calendar": (CALENDAR_EVENTS,),
    "classroom": (
        CLASSROOM_COURSES,
        CLASSROOM_COURSEWORK,
        CLASSROOM_ANNOUNCEMENTS,
        CLASSROOM_MATERIALS,
    ),
    "drive": (DRIVE_READONLY, DRIVE_FILE),
}
_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - public endpoint


class GoogleNotConfigured(RuntimeError):
    """The OAuth client or the account's token is missing, or lacks a needed scope."""


def token_secret_name(account: str) -> str:
    return f"google_oauth:{account}"


def scopes_for(services: Iterable[str]) -> tuple[str, ...]:
    """Scopes for the named services, in a stable order. Unknown names raise ``ValueError``."""
    scopes: dict[str, None] = {}
    for service in services:
        if service not in SERVICE_SCOPES:
            raise ValueError(f"unknown Google service: {service}")
        scopes.update(dict.fromkeys(SERVICE_SCOPES[service]))
    return tuple(scopes)


def merged_scopes(existing_token_json: str | None, services: Iterable[str]) -> tuple[str, ...]:
    """Scopes to request: those already granted, those for ``services`` and the identity scopes."""
    merged = granted_scopes(existing_token_json) | frozenset(scopes_for(services))
    return tuple(sorted(merged | frozenset(IDENTITY_SCOPES)))


def granted_scopes(token_json: str | None) -> frozenset[str]:
    """Scopes recorded in a stored token, or none if there is no token."""
    if token_json is None:
        return frozenset()
    info = json.loads(token_json)
    raw = info.get("scopes") or []
    if isinstance(raw, str):
        raw = raw.split()
    return normalise_scopes(str(s) for s in raw)


def client_config(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    inner = data.get("installed") or data.get("web") or data
    config: dict[str, Any] = inner
    return config


class GoogleAuth:
    """Loads and caches one ``Credentials`` per account and persists refreshed tokens."""

    def __init__(self, keystore: KeyStore) -> None:
        self._keystore = keystore
        self._cache: dict[str, Credentials] = {}
        self._saved: dict[str, str | None] = {}
        self._lock = threading.Lock()

    def credentials(self, account: str, required: Iterable[str]) -> Credentials:
        """The account's shared credential. Raises if any ``required`` scope was not granted."""
        needed = frozenset(required)
        with self._lock:
            creds = self._cache.get(account)
            if creds is None:
                creds = self._load(account)
                self._cache[account] = creds
                self._saved[account] = creds.token
            granted = normalise_scopes(creds.scopes or ())
            if not needed <= granted:
                raise GoogleNotConfigured(
                    "account token lacks a required scope; re-run setup_google_oauth.py"
                )
            return creds

    def _load(self, account: str) -> Credentials:
        client_raw = self._keystore.get(CLIENT_SECRET_NAME)
        token_raw = self._keystore.get(token_secret_name(account))
        if client_raw is None or token_raw is None:
            raise GoogleNotConfigured("google oauth client or account token missing from keyring")
        client = client_config(client_raw)
        info: dict[str, Any] = json.loads(token_raw)
        info.setdefault("client_id", client.get("client_id"))
        info.setdefault("client_secret", client.get("client_secret"))
        info.setdefault("token_uri", client.get("token_uri", _TOKEN_URI))
        scopes = sorted(granted_scopes(token_raw))
        creds: Credentials = Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
            info, scopes=scopes
        )
        return creds

    def persist_hook(self, account: str) -> Callable[[], None]:
        """A callback for connectors to run after each API call; saves a refreshed token."""

        def persist() -> None:
            with self._lock:
                creds = self._cache.get(account)
                if creds is not None and creds.token != self._saved.get(account):
                    self._keystore.set(token_secret_name(account), creds.to_json())  # type: ignore[no-untyped-call]
                    self._saved[account] = creds.token

        return persist
