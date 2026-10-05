from __future__ import annotations

import pytest

from agent.store.crypto import DecryptionError, FieldCipher

KEY = bytes(range(32))
AAD = "pending_actions.payload:abc"


def test_round_trip() -> None:
    c = FieldCipher(KEY)
    blob = c.encrypt("hello", AAD)
    assert blob[:1] == b"\x01"
    assert c.decrypt(blob, AAD) == b"hello"
    assert c.decrypt_str(c.encrypt(b"bytes", AAD), AAD) == "bytes"


def test_unique_nonce_per_call() -> None:
    c = FieldCipher(KEY)
    a, b = c.encrypt("same", AAD), c.encrypt("same", AAD)
    assert a != b
    assert a[1:13] != b[1:13]


def test_wrong_aad_fails() -> None:
    c = FieldCipher(KEY)
    with pytest.raises(DecryptionError):
        c.decrypt(c.encrypt("x", AAD), "pending_actions.payload:other")


def test_tamper_fails() -> None:
    c = FieldCipher(KEY)
    blob = bytearray(c.encrypt("x", AAD))
    blob[-1] ^= 1
    with pytest.raises(DecryptionError):
        c.decrypt(bytes(blob), AAD)


def test_wrong_version_and_truncation_fail() -> None:
    c = FieldCipher(KEY)
    blob = c.encrypt("x", AAD)
    with pytest.raises(DecryptionError):
        c.decrypt(b"\x02" + blob[1:], AAD)
    with pytest.raises(DecryptionError):
        c.decrypt(blob[:10], AAD)


def test_wrong_key_fails() -> None:
    blob = FieldCipher(KEY).encrypt("x", AAD)
    with pytest.raises(DecryptionError):
        FieldCipher(bytes(32)).decrypt(blob, AAD)


@pytest.mark.parametrize("n", [0, 16, 31, 33])
def test_bad_key_length(n: int) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        FieldCipher(bytes(n))
