from __future__ import annotations

import base64
import hashlib

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import chainer, fail, null
from keyring.errors import PasswordSetError

from agent.store.keystore import (
    CHUNK_CHARS,
    SERVICE,
    InsecureKeyringError,
    KeyStore,
    KeyStoreCorrupt,
    assert_secure_backend,
)
from tests.conftest import InMemoryKeyring, SizeLimitedKeyring

PREFIX = "personalai-chunked/v1;"


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


def _entries(backend: InMemoryKeyring) -> dict[str, str]:
    return {user: value for (_, user), value in backend._store.items()}


def _chunk_names(backend: InMemoryKeyring, name: str) -> list[str]:
    return [user for user in _entries(backend) if user.startswith(f"{name}#chunk:")]


@pytest.mark.parametrize(
    "value",
    [
        "a" * 10_000,
        "\U0001f600\u0928\u092e\u0938\u094d\u0924\u0947 token " * 400,
        "\U0001f600" * 3000,
    ],
)
def test_long_values_round_trip_within_backend_limit(
    size_limited_keyring: SizeLimitedKeyring, value: str
) -> None:
    ks = KeyStore()
    ks.set("big", value)
    assert ks.get("big") == value
    for stored in size_limited_keyring._store.values():
        assert len(stored.encode("utf-16-le")) <= SizeLimitedKeyring.LIMIT_BYTES


@pytest.mark.parametrize("length", [511, 512, 513])
def test_boundary_lengths(size_limited_keyring: SizeLimitedKeyring, length: int) -> None:
    ks = KeyStore()
    ks.set("k", "x" * length)
    assert ks.get("k") == "x" * length
    chunked = length > CHUNK_CHARS
    assert bool(_chunk_names(size_limited_keyring, "k")) is chunked
    assert size_limited_keyring._store[(SERVICE, "k")].startswith(PREFIX) is chunked


def test_short_values_are_stored_verbatim(in_memory_keyring: InMemoryKeyring) -> None:
    KeyStore().set("k", "plain")
    assert in_memory_keyring._store[(SERVICE, "k")] == "plain"


def test_old_format_short_entry_still_readable(in_memory_keyring: InMemoryKeyring) -> None:
    in_memory_keyring._store[(SERVICE, "legacy")] = "old-value"
    assert KeyStore().get("legacy") == "old-value"


def test_short_value_with_header_prefix_round_trips(in_memory_keyring: InMemoryKeyring) -> None:
    ks = KeyStore()
    value = PREFIX + "gen=deadbeef;n=1;sha256=" + "0" * 64
    ks.set("k", value)
    assert ks.get("k") == value
    assert _chunk_names(in_memory_keyring, "k")


def test_overwrite_long_with_long_leaves_no_orphans(
    size_limited_keyring: SizeLimitedKeyring,
) -> None:
    ks = KeyStore()
    ks.set("k", "a" * 5000)
    ks.set("k", "b" * 1200)
    assert ks.get("k") == "b" * 1200
    assert len(_chunk_names(size_limited_keyring, "k")) == 3
    assert len(_entries(size_limited_keyring)) == 4


def test_overwrite_long_with_short_removes_chunks(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    ks.set("k", "a" * 5000)
    ks.set("k", "short")
    assert ks.get("k") == "short"
    assert _entries(size_limited_keyring) == {"k": "short"}


def test_overwrite_short_with_long(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    ks.set("k", "short")
    ks.set("k", "a" * 2000)
    assert ks.get("k") == "a" * 2000
    assert len(_chunk_names(size_limited_keyring, "k")) == 4


def test_delete_removes_header_and_chunks(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    ks.set("k", "a" * 5000)
    ks.set("other", "keep")
    ks.delete("k")
    assert ks.get("k") is None
    assert _entries(size_limited_keyring) == {"other": "keep"}


def test_missing_chunk_raises_corrupt(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    ks.set("k", "secret-" + "a" * 2000)
    del size_limited_keyring._store[(SERVICE, _chunk_names(size_limited_keyring, "k")[1])]
    with pytest.raises(KeyStoreCorrupt) as info:
        ks.get("k")
    assert "secret-" not in str(info.value)


def test_tampered_chunk_raises_corrupt(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    ks.set("k", "a" * 2000)
    size_limited_keyring._store[(SERVICE, _chunk_names(size_limited_keyring, "k")[0])] = "b" * 512
    with pytest.raises(KeyStoreCorrupt):
        ks.get("k")


@pytest.mark.parametrize(
    "header",
    [
        PREFIX + "garbage",
        PREFIX + "gen=deadbeef;n=0;sha256=" + "0" * 64,
        PREFIX + "gen=deadbeef;n=257;sha256=" + "0" * 64,
    ],
)
def test_bad_header_raises_corrupt(in_memory_keyring: InMemoryKeyring, header: str) -> None:
    in_memory_keyring._store[(SERVICE, "k")] = header
    with pytest.raises(KeyStoreCorrupt):
        KeyStore().get("k")


def test_too_many_chunks_refused(size_limited_keyring: SizeLimitedKeyring) -> None:
    with pytest.raises(ValueError):
        KeyStore().set("k", "a" * (CHUNK_CHARS * 256 + 1))
    assert _entries(size_limited_keyring) == {}


def test_bytes_round_trip_4kb(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    data = bytes(range(256)) * 16
    ks.set_bytes("blob", data)
    assert ks.get_bytes("blob") == data
    assert hashlib.sha256(ks.get_bytes("blob") or b"").digest() == hashlib.sha256(data).digest()


def test_interrupted_overwrite_keeps_old_value(size_limited_keyring: SizeLimitedKeyring) -> None:
    ks = KeyStore()
    ks.set("k", "a" * 3000)
    real_set = size_limited_keyring.set_password

    def failing_set(service: str, username: str, password: str) -> None:
        if username == "k":
            raise PasswordSetError("interrupted")
        real_set(service, username, password)

    size_limited_keyring.set_password = failing_set  # type: ignore[method-assign]
    with pytest.raises(PasswordSetError):
        ks.set("k", "b" * 3000)
    assert ks.get("k") == "a" * 3000
    assert keyring.get_password(SERVICE, "k") is not None
