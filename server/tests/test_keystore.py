from __future__ import annotations

import base64

import pytest
from keyring.backend import KeyringBackend
from keyring.backends import chainer, fail, null

from agent.store.keystore import InsecureKeyringError, KeyStore, assert_secure_backend
from tests.conftest import InMemoryKeyring


def _fake(module: str, qualname: str) -> KeyringBackend:
    cls = type(
        qualname,
        (KeyringBackend,),
        {
            "priority": 1,
            "__module__": module,
            "__qualname__": qualname,
            "get_password": lambda self, s, u: None,
            "set_password": lambda self, s, u, p: None,
            "delete_password": lambda self, s, u: None,
        },
    )
    return cls()  # type: ignore[no-any-return]


def _chain(*members: KeyringBackend) -> chainer.ChainerBackend:
    # ``backends`` is a classproperty on the real class, so override it on a subclass.
    cls = type("ChainerBackend", (chainer.ChainerBackend,), {"backends": list(members)})
    cls.__module__ = chainer.ChainerBackend.__module__
    return cls()  # type: ignore[no-any-return]


@pytest.mark.parametrize("backend", [fail.Keyring(), null.Keyring(), InMemoryKeyring()])
def test_insecure_backends_refused(backend: KeyringBackend) -> None:
    with pytest.raises(InsecureKeyringError):
        assert_secure_backend(backend)


def test_chainer_with_fail_backend_refused() -> None:
    win = _fake("keyring.backends.Windows", "WinVaultKeyring")
    with pytest.raises(InsecureKeyringError):
        assert_secure_backend(_chain(win, fail.Keyring()))


def test_empty_chainer_refused() -> None:
    with pytest.raises(InsecureKeyringError):
        assert_secure_backend(_chain())


def test_allowlisted_backend_accepted() -> None:
    win = _fake("keyring.backends.Windows", "WinVaultKeyring")
    assert_secure_backend(win)
    assert_secure_backend(_chain(win))


def test_keystore_round_trip_and_delete() -> None:
    ks = KeyStore()
    assert ks.get("x") is None
    ks.set("x", "v")
    assert ks.get("x") == "v"
    ks.delete("x")
    ks.delete("x")
    assert ks.get("x") is None


def test_get_or_create_bytes_is_stable_and_urlsafe() -> None:
    ks = KeyStore()
    first = ks.get_or_create_bytes("db_key")
    assert len(first) == 32
    assert ks.get_or_create_bytes("db_key") == first
    stored = ks.get("db_key")
    assert stored is not None
    assert base64.urlsafe_b64decode(stored + "=" * (-len(stored) % 4)) == first
