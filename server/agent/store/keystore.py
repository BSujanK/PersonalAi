"""OS keyring access. Refuses insecure backends; there is no plaintext fallback."""

from __future__ import annotations

import base64
import contextlib
import secrets

import keyring
import keyring.errors
from keyring.backend import KeyringBackend

SERVICE = "PersonalAi"

_ALLOWED_BACKENDS = frozenset(
    {
        "keyring.backends.Windows.WinVaultKeyring",
        "keyring.backends.macOS.Keyring",
        "keyring.backends.SecretService.Keyring",
        "keyring.backends.libsecret.Keyring",
        "keyring.backends.kwallet.DBusKeyring",
    }
)
_CHAINER = "keyring.backends.chainer.ChainerBackend"


class InsecureKeyringError(RuntimeError):
    """Raised when the active keyring backend is not an OS-protected store."""


def _qualified_name(backend: object) -> str:
    cls = type(backend)
    return f"{cls.__module__}.{cls.__qualname__}"


def assert_secure_backend(backend: KeyringBackend | None = None) -> None:
    active = backend if backend is not None else keyring.get_keyring()
    name = _qualified_name(active)
    if name == _CHAINER:
        members = list(getattr(active, "backends", []))
        if members and all(_qualified_name(m) in _ALLOWED_BACKENDS for m in members):
            return
        raise InsecureKeyringError("keyring chainer contains no backends or an insecure backend")
    if name not in _ALLOWED_BACKENDS:
        raise InsecureKeyringError(f"insecure keyring backend: {name}")


class KeyStore:
    """Thin wrapper so the globally configured keyring backend is always used."""

    def get(self, name: str) -> str | None:
        return keyring.get_password(SERVICE, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(SERVICE, name)

    def get_or_create_bytes(self, name: str, n: int = 32) -> bytes:
        existing = self.get(name)
        if existing is not None:
            return base64.urlsafe_b64decode(existing + "=" * (-len(existing) % 4))
        value = secrets.token_bytes(n)
        self.set(name, base64.urlsafe_b64encode(value).decode("ascii"))
        return value
