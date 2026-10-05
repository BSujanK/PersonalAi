"""OS keyring access. Refuses insecure backends; there is no plaintext fallback."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import re
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

# Windows Credential Manager rejects secrets over ~1280 characters (2560 bytes of UTF-16), so
# longer values are split. 512 code points stay under the limit even when every one is non-BMP.
CHUNK_CHARS = 512
MAX_CHUNKS = 256
_HEADER_PREFIX = "personalai-chunked/v1;"
_HEADER_RE = re.compile(
    r"personalai-chunked/v1;gen=([0-9a-f]{8});n=([0-9]{1,3});sha256=([0-9a-f]{64})"
)


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


class KeyStoreCorrupt(RuntimeError):
    """A chunked secret is malformed, incomplete or fails its integrity check."""


def _chunk_name(name: str, gen: str, index: int) -> str:
    return f"{name}#chunk:{gen}:{index}"


def _parse_header(raw: str) -> tuple[str, int, str] | None:
    """``(gen, chunk count, sha256)`` of a chunk header, or ``None`` if ``raw`` is not valid."""
    match = _HEADER_RE.fullmatch(raw)
    if match is None:
        return None
    count = int(match.group(2))
    if not 1 <= count <= MAX_CHUNKS:
        return None
    return match.group(1), count, match.group(3)


class KeyStore:
    """Thin wrapper so the globally configured keyring backend is always used.

    Values longer than ``CHUNK_CHARS`` are stored as numbered chunk entries plus a header entry at
    ``name``. Chunks are written before the header and old chunks are removed after it, so an
    interrupted overwrite never leaves a header pointing at partial data.
    """

    def get(self, name: str) -> str | None:
        raw = keyring.get_password(SERVICE, name)
        if raw is None or not raw.startswith(_HEADER_PREFIX):
            return raw
        header = _parse_header(raw)
        if header is None:
            raise KeyStoreCorrupt(f"keyring entry {name!r} has an invalid chunk header")
        gen, count, digest = header
        parts: list[str] = []
        for index in range(count):
            part = keyring.get_password(SERVICE, _chunk_name(name, gen, index))
            if part is None:
                raise KeyStoreCorrupt(f"keyring entry {name!r} is missing chunk {index}")
            parts.append(part)
        value = "".join(parts)
        if hashlib.sha256(value.encode("utf-8")).hexdigest() != digest:
            raise KeyStoreCorrupt(f"keyring entry {name!r} failed its integrity check")
        return value

    def set(self, name: str, value: str) -> None:
        previous = keyring.get_password(SERVICE, name)
        if len(value) <= CHUNK_CHARS and not value.startswith(_HEADER_PREFIX):
            keyring.set_password(SERVICE, name, value)
        else:
            chunks = [value[i : i + CHUNK_CHARS] for i in range(0, len(value), CHUNK_CHARS)]
            if len(chunks) > MAX_CHUNKS:
                raise ValueError("secret is too long to store in the keyring")
            gen = secrets.token_hex(4)
            for index, chunk in enumerate(chunks):
                keyring.set_password(SERVICE, _chunk_name(name, gen, index), chunk)
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            keyring.set_password(
                SERVICE, name, f"{_HEADER_PREFIX}gen={gen};n={len(chunks)};sha256={digest}"
            )
        self._delete_chunks(name, previous)

    def delete(self, name: str) -> None:
        previous = keyring.get_password(SERVICE, name)
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(SERVICE, name)
        self._delete_chunks(name, previous)

    def _delete_chunks(self, name: str, header_raw: str | None) -> None:
        """Remove the chunks a header refers to, unless that generation is still the live one."""
        if header_raw is None or not header_raw.startswith(_HEADER_PREFIX):
            return
        header = _parse_header(header_raw)
        if header is None:
            return
        gen, count, _ = header
        if keyring.get_password(SERVICE, name) == header_raw:
            return
        for index in range(count):
            with contextlib.suppress(keyring.errors.PasswordDeleteError):
                keyring.delete_password(SERVICE, _chunk_name(name, gen, index))

    def get_bytes(self, name: str) -> bytes | None:
        existing = self.get(name)
        if existing is None:
            return None
        return base64.urlsafe_b64decode(existing + "=" * (-len(existing) % 4))

    def set_bytes(self, name: str, value: bytes) -> None:
        self.set(name, base64.urlsafe_b64encode(value).decode("ascii"))

    def get_or_create_bytes(self, name: str, n: int = 32) -> bytes:
        existing = self.get_bytes(name)
        if existing is not None:
            return existing
        value = secrets.token_bytes(n)
        self.set_bytes(name, value)
        return value
