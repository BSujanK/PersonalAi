"""Shared fixtures. Tests never touch the real OS keyring."""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError, PasswordSetError


class InMemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]
    # Never auto-discovered: keyring's chainer would otherwise add this test backend next to the
    # real OS store in any process that merely imports it (e.g. scripts/eval_models.py). Tests
    # install it explicitly with keyring.set_keyring, which does not check viability.
    viable = False  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self._store[(service, username)]
        except KeyError:
            raise PasswordDeleteError("not found") from None


@pytest.fixture(autouse=True)
def in_memory_keyring() -> Iterator[InMemoryKeyring]:
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


class SizeLimitedKeyring(InMemoryKeyring):
    """Mimics Windows Credential Manager, which rejects secrets over 2560 bytes of UTF-16."""

    LIMIT_BYTES = 2560

    def set_password(self, service: str, username: str, password: str) -> None:
        if len(password.encode("utf-16-le")) > self.LIMIT_BYTES:
            raise PasswordSetError("secret too long")
        super().set_password(service, username, password)


@pytest.fixture
def size_limited_keyring() -> SizeLimitedKeyring:
    backend = SizeLimitedKeyring()
    keyring.set_keyring(backend)  # the autouse fixture restores the previous backend
    return backend
