"""Allowlisted local files: path confinement and an index that stores only keyed word hashes."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent.connectors.textextract import SUPPORTED_SUFFIXES, extract_text
from agent.core.clock import Clock
from agent.store.crypto import FieldCipher
from agent.store.db import Database

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_WALKED_FILES = 50_000
MAX_TOKENS_PER_FILE = 100_000
_PATH_LABEL = b"personalai/file-path/v1"
_TOKEN_LABEL = b"personalai/file-token/v1"
_WORD = re.compile(r"\w{2,40}")


class FileAccessDenied(PermissionError):
    """The path is outside the allowed folders or is not a readable, supported file."""


def _parts(path: Path) -> tuple[str, ...]:
    return tuple(os.path.normcase(part) for part in path.parts)


class FileRoots:
    def __init__(self, roots: Sequence[str]) -> None:
        resolved: list[Path] = []
        for root in roots:
            path = Path(root)
            if not path.is_absolute() or not path.is_dir():
                raise ValueError("each file root must be an absolute existing directory")
            resolved.append(path.resolve(strict=True))
        self._roots = tuple(resolved)

    def _relative(self, path: Path) -> tuple[str, ...] | None:
        """Components of ``path`` below the root that contains it, or None if outside all."""
        target = _parts(path)
        for root in self._roots:
            base = _parts(root)
            if target[: len(base)] == base:
                return path.parts[len(base) :]
        return None

    def resolve_inside(self, path: str) -> Path:
        try:
            resolved = Path(path).resolve(strict=True)
            relative = self._relative(resolved)
            if relative is None or any(part.startswith(".") for part in relative):
                raise FileAccessDenied("path is not allowed")
            if not resolved.is_file() or resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise FileAccessDenied("path is not allowed")
            if resolved.stat().st_size > MAX_FILE_BYTES:
                raise FileAccessDenied("path is not allowed")
        except FileAccessDenied:
            raise
        except (OSError, ValueError, RuntimeError):
            raise FileAccessDenied("path is not allowed") from None
        return resolved

    def walk(self) -> Iterator[Path]:
        count = 0
        for root in self._roots:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                here = Path(dirpath)
                dirnames[:] = [
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and not (here / d).is_symlink()
                    and not (here / d).is_junction()
                ]
                for filename in filenames:
                    path = here / filename
                    if filename.startswith(".") or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                        continue
                    try:
                        if path.is_symlink() or path.is_junction():
                            continue
                        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                            continue
                    except OSError:
                        continue
                    if count >= MAX_WALKED_FILES:
                        return
                    count += 1
                    yield path


@dataclass(frozen=True)
class FileHit:
    path: str
    name: str
    size: int
    modified: str


class FileIndex:
    def __init__(
        self, db: Database, cipher: FieldCipher, db_key: bytes, roots: FileRoots, clock: Clock
    ) -> None:
        self._db = db
        self._cipher = cipher
        self._path_key = hmac.new(db_key, _PATH_LABEL, hashlib.sha256).digest()
        self._token_key = hmac.new(db_key, _TOKEN_LABEL, hashlib.sha256).digest()
        self._roots = roots
        self._clock = clock

    def path_hash(self, path: Path) -> str:
        data = os.path.normcase(str(path)).encode()
        return hmac.new(self._path_key, data, hashlib.sha256).hexdigest()

    def _word(self, word: str) -> str:
        return hmac.new(self._token_key, word.encode(), hashlib.sha256).digest()[:8].hex()

    def tokens(self, text: str) -> str:
        words = (m.group() for m in _WORD.finditer(text.casefold()))
        out: list[str] = []
        for word in words:
            out.append(self._word(word))
            if len(out) >= MAX_TOKENS_PER_FILE:
                break
        return " ".join(out)

    @staticmethod
    def _aad(path_hash: str) -> str:
        return f"local_files.path:{path_hash}"

    def refresh(self) -> tuple[int, int]:
        """Index new and changed files and drop vanished ones. Returns (indexed, removed)."""
        indexed = skipped = 0
        seen: set[str] = set()
        known = {
            row["path_hash"]: (row["size"], row["mtime_ns"])
            for row in self._db.query("SELECT path_hash, size, mtime_ns FROM local_files")
        }
        for path in self._roots.walk():
            try:
                stat = path.stat()
                digest = self.path_hash(path)
                seen.add(digest)
                if known.get(digest) == (stat.st_size, stat.st_mtime_ns):
                    continue
                text = extract_text(path.read_bytes(), path.suffix)
            except OSError:
                skipped += 1
                continue
            with self._db.transaction():
                self._db.execute(
                    "INSERT INTO local_files (path_hash, path_enc, size, mtime_ns, indexed_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(path_hash) DO UPDATE SET "
                    "size = excluded.size, mtime_ns = excluded.mtime_ns, "
                    "indexed_at = excluded.indexed_at",
                    (
                        digest,
                        self._cipher.encrypt(str(path), self._aad(digest)),
                        stat.st_size,
                        stat.st_mtime_ns,
                        self._clock().isoformat(),
                    ),
                )
                row = self._db.query("SELECT id FROM local_files WHERE path_hash = ?", (digest,))[0]
                self._db.execute("DELETE FROM local_files_fts WHERE rowid = ?", (row["id"],))
                self._db.execute(
                    "INSERT INTO local_files_fts (rowid, tokens) VALUES (?, ?)",
                    (row["id"], self.tokens(text)),
                )
            indexed += 1
        removed = 0
        with self._db.transaction():
            for stale in known.keys() - seen:
                row = self._db.query("SELECT id FROM local_files WHERE path_hash = ?", (stale,))[0]
                self._db.execute("DELETE FROM local_files_fts WHERE rowid = ?", (row["id"],))
                self._db.execute("DELETE FROM local_files WHERE id = ?", (row["id"],))
                removed += 1
        log.info(
            "file index refreshed: indexed=%d removed=%d skipped=%d", indexed, removed, skipped
        )
        return indexed, removed

    def search(self, query: str, limit: int) -> list[FileHit]:
        words = [m.group() for m in _WORD.finditer(query.casefold())]
        if not words:
            return []
        match = " ".join(f'"{self._word(word)}"' for word in dict.fromkeys(words))
        rows = self._db.query(
            "SELECT f.path_hash, f.path_enc, f.size, f.mtime_ns FROM local_files_fts "
            "JOIN local_files f ON f.id = local_files_fts.rowid "
            "WHERE local_files_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        )
        hits: list[FileHit] = []
        for row in rows:
            raw = self._cipher.decrypt_str(row["path_enc"], self._aad(row["path_hash"]))
            try:
                path = self._roots.resolve_inside(raw)
                stat = path.stat()
            except (FileAccessDenied, OSError):
                continue
            modified = datetime.fromtimestamp(stat.st_mtime, tz=self._clock().tzinfo).isoformat()
            hits.append(FileHit(str(path), path.name, stat.st_size, modified))
        return hits
