"""AES-256-GCM column encryption. AAD binds a ciphertext to its table, column and row."""

from __future__ import annotations

import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"\x01"
_NONCE_LEN = 12


class DecryptionError(Exception):
    """Raised when a blob cannot be authenticated or decrypted."""


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str | bytes, aad: str) -> bytes:
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        nonce = secrets.token_bytes(_NONCE_LEN)
        return _VERSION + nonce + self._aead.encrypt(nonce, data, aad.encode("utf-8"))

    def decrypt(self, blob: bytes, aad: str) -> bytes:
        if len(blob) < 1 + _NONCE_LEN + 16 or blob[:1] != _VERSION:
            raise DecryptionError("unsupported or truncated ciphertext")
        nonce = blob[1 : 1 + _NONCE_LEN]
        try:
            return self._aead.decrypt(nonce, blob[1 + _NONCE_LEN :], aad.encode("utf-8"))
        except InvalidTag:
            raise DecryptionError("authentication failed") from None

    def decrypt_str(self, blob: bytes, aad: str) -> str:
        try:
            return self.decrypt(blob, aad).decode("utf-8")
        except UnicodeDecodeError:
            raise DecryptionError("plaintext is not valid UTF-8") from None
