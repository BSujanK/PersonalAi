"""Shared fixtures. Tests never touch the real OS keyring."""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class InMemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

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
