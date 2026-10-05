"""Encrypted backup and restore of the SQLite database.

A backup is a single file protected by a passphrase. Layout::

    b"PAIBAK1\\n"                     magic
    <header JSON, UTF-8>  b"\\n"      {"v", "kdf", "n", "r", "p", "salt", "nonce",
                                      "created_at", "schema_version"}; binary fields base64
    <AES-256-GCM ciphertext + tag>   key = scrypt(passphrase, salt); AAD = magic + header line

The plaintext is ``<4-byte big-endian length L><L bytes of JSON {"db_key": base64}><SQLite bytes>``.

The backup carries the ``db_key`` because encrypted columns are unreadable without it on a new
machine. No other keyring secret is included: after a restore the owner must re-pair the phone
and re-authorise Google and the NVIDIA key. Passphrases, keys and row content are never logged.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
import os
import secrets
import sqlite3
import struct
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from agent.core.clock import Clock, utcnow
from agent.store.db import SCHEMA_VERSION
from agent.store.keystore import KeyStore

MAGIC = b"PAIBAK1\n"
MIN_PASSPHRASE_CHARS = 12
DEFAULT_SCRYPT_N = 2**17
MIN_SCRYPT_N = 2**14
MAX_SCRYPT_N = 2**20
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32
_MAX_HEADER_BYTES = 1024
_LEN_PREFIX = struct.Struct(">I")
_DECRYPT_FAILED = "cannot decrypt backup: wrong passphrase or file is corrupted"
_INVALID_FILE = "not a valid PersonalAi backup file"


class BackupError(Exception):
    """A backup or restore was refused or failed."""


def _derive_key(passphrase: str, salt: bytes, n: int) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_LEN, n=n, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def _check_passphrase(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE_CHARS:
        raise BackupError(f"passphrase must be at least {MIN_PASSPHRASE_CHARS} characters")


def _snapshot(db_path: Path) -> bytes:
    """A consistent copy of the live database, serialized to bytes."""
    if not db_path.is_file():
        raise BackupError(f"database not found: {db_path}")
    with tempfile.TemporaryDirectory(prefix="personalai-backup-") as tmp:
        snap_path = Path(tmp) / "snapshot.db"
        fd = os.open(snap_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        source = sqlite3.connect(db_path)
        snap = sqlite3.connect(snap_path)
        try:
            source.backup(snap)
            snap.execute("PRAGMA journal_mode=DELETE")
            return snap.serialize()
        except sqlite3.Error as exc:
            raise BackupError(f"cannot snapshot database: {type(exc).__name__}") from None
        finally:
            snap.close()
            source.close()


def _write_new_file(path: Path, data: bytes) -> None:
    """Atomically create ``path`` with 0o600; never overwrites an existing file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        raise BackupError(f"temporary file already exists: {tmp}") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def create_backup(
    db_path: Path,
    out_path: Path,
    passphrase: str,
    keystore: KeyStore,
    now: Clock,
    *,
    scrypt_n: int = DEFAULT_SCRYPT_N,
) -> None:
    """Write an encrypted snapshot of ``db_path`` (plus ``db_key``) to ``out_path``."""
    _check_passphrase(passphrase)
    if not MIN_SCRYPT_N <= scrypt_n <= MAX_SCRYPT_N:
        raise BackupError("scrypt cost parameter out of range")
    if out_path.exists():
        raise BackupError(f"refusing to overwrite existing file: {out_path}")
    db_key = keystore.get_bytes("db_key")
    if db_key is None:
        raise BackupError("no db_key in the keyring: nothing to back up")
    sqlite_bytes = _snapshot(db_path)
    key_json = json.dumps({"db_key": base64.b64encode(db_key).decode("ascii")}).encode("ascii")
    plaintext = _LEN_PREFIX.pack(len(key_json)) + key_json + sqlite_bytes
    salt = secrets.token_bytes(_SALT_LEN)
    nonce = secrets.token_bytes(_NONCE_LEN)
    header = {
        "v": 1,
        "kdf": "scrypt",
        "n": scrypt_n,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "created_at": now().isoformat(),
        "schema_version": SCHEMA_VERSION,
    }
    header_line = json.dumps(header, separators=(",", ":")).encode("utf-8") + b"\n"
    key = _derive_key(passphrase, salt, scrypt_n)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, MAGIC + header_line)
    _write_new_file(out_path, MAGIC + header_line + ciphertext)


def _b64_field(header: dict[str, Any], name: str, length: int) -> bytes:
    value = header.get(name)
    if not isinstance(value, str):
        raise BackupError(_INVALID_FILE)
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise BackupError(_INVALID_FILE) from None
    if len(raw) != length:
        raise BackupError(_INVALID_FILE)
    return raw


def _parse_header(blob: bytes) -> tuple[dict[str, Any], bytes, bytes, bytes, int]:
    """``(header, aad, salt, nonce, n)`` and the ciphertext offset is ``len(aad)``."""
    if not blob.startswith(MAGIC):
        raise BackupError(_INVALID_FILE)
    end = blob.find(b"\n", len(MAGIC), len(MAGIC) + _MAX_HEADER_BYTES)
    if end == -1:
        raise BackupError(_INVALID_FILE)
    aad = blob[: end + 1]
    try:
        header = json.loads(blob[len(MAGIC) : end].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BackupError(_INVALID_FILE) from None
    if not isinstance(header, dict):
        raise BackupError(_INVALID_FILE)
    n = header.get("n")
    if (
        header.get("v") != 1
        or header.get("kdf") != "scrypt"
        or header.get("r") != _SCRYPT_R
        or header.get("p") != _SCRYPT_P
        or not isinstance(n, int)
        or isinstance(n, bool)
        or n & (n - 1)
        or not MIN_SCRYPT_N <= n <= MAX_SCRYPT_N
    ):
        raise BackupError("unsupported backup format or parameters")
    salt = _b64_field(header, "salt", _SALT_LEN)
    nonce = _b64_field(header, "nonce", _NONCE_LEN)
    return header, aad, salt, nonce, n


def _decrypt(blob: bytes, passphrase: str) -> tuple[dict[str, Any], bytes, bytes]:
    """``(header, db_key, sqlite bytes)`` from a backup file's contents."""
    header, aad, salt, nonce, n = _parse_header(blob)
    ciphertext = blob[len(aad) :]
    if len(ciphertext) < 16:
        raise BackupError(_INVALID_FILE)
    try:
        plaintext = AESGCM(_derive_key(passphrase, salt, n)).decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise BackupError(_DECRYPT_FAILED) from None
    if len(plaintext) < _LEN_PREFIX.size:
        raise BackupError(_INVALID_FILE)
    (key_len,) = _LEN_PREFIX.unpack_from(plaintext)
    key_end = _LEN_PREFIX.size + key_len
    if key_len > 256 or len(plaintext) <= key_end:
        raise BackupError(_INVALID_FILE)
    try:
        key_doc = json.loads(plaintext[_LEN_PREFIX.size : key_end].decode("ascii"))
        if not isinstance(key_doc, dict) or set(key_doc) != {"db_key"}:
            raise ValueError
        db_key = base64.b64decode(key_doc["db_key"], validate=True)
    except (UnicodeDecodeError, ValueError, TypeError, binascii.Error):
        raise BackupError(_INVALID_FILE) from None
    if len(db_key) != _KEY_LEN:
        raise BackupError(_INVALID_FILE)
    return header, db_key, plaintext[key_end:]


def _validate_sqlite(data: bytes) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(data)
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("backup database failed its integrity check")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error:
        raise BackupError("backup does not contain a valid database") from None
    finally:
        conn.close()
    if not 1 <= version <= SCHEMA_VERSION:
        raise BackupError(
            f"backup schema version {version} is not supported (this server supports "
            f"up to {SCHEMA_VERSION}); upgrade the server first"
        )


def _read_backup(in_path: Path) -> bytes:
    try:
        return in_path.read_bytes()
    except OSError as exc:
        raise BackupError(f"cannot read backup file: {type(exc).__name__}") from None


def restore_backup(
    in_path: Path,
    db_path: Path,
    passphrase: str,
    keystore: KeyStore,
    *,
    force: bool,
    now: Clock = utcnow,
) -> None:
    """Decrypt ``in_path`` into ``db_path`` and install its ``db_key`` in the keyring.

    Stop the server first. Existing data is moved aside, never deleted, and only with ``force``.
    """
    _, db_key, sqlite_bytes = _decrypt(_read_backup(in_path), passphrase)
    _validate_sqlite(sqlite_bytes)
    existing_key = keystore.get_bytes("db_key")
    if db_path.exists() and not force:
        raise BackupError(f"database already exists: {db_path} (use --force to replace it)")
    if existing_key is not None and not secrets.compare_digest(existing_key, db_key) and not force:
        raise BackupError(
            "the keyring already holds a different db_key; replacing it would make the "
            "existing database unreadable (use --force to replace both)"
        )
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    if existing_key is not None and not secrets.compare_digest(existing_key, db_key):
        # Keep the old key next to the old database, or the moved-aside copy is unreadable.
        keystore.set_bytes(f"db_key.pre-restore-{stamp}", existing_key)
    _move_aside(db_path, stamp)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _write_new_file(db_path, sqlite_bytes)
    keystore.set_bytes("db_key", db_key)


def _move_aside(db_path: Path, stamp: str) -> None:
    """Rename the database and its WAL/SHM siblings to ``<name>.pre-restore-<stamp>[-wal|-shm]``."""
    for suffix in ("", "-wal", "-shm"):
        src = db_path.with_name(db_path.name + suffix)
        if src.exists():
            os.replace(src, db_path.with_name(f"{db_path.name}.pre-restore-{stamp}{suffix}"))
