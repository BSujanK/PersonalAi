from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest

from agent.connectors import files as files_module
from agent.connectors.files import MAX_FILE_BYTES, FileAccessDenied, FileIndex, FileRoots
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from tests.support import FakeClock

KEY = bytes(range(32))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    return root


def _index(tmp_path: Path, root: Path) -> tuple[FileIndex, Database, FileRoots]:
    roots = FileRoots([str(root)])
    db = Database(tmp_path / "state" / "agent.db")
    return FileIndex(db, FieldCipher(KEY), KEY, roots, FakeClock()), db, roots


def test_roots_must_be_absolute_existing_dirs(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        FileRoots(["relative/dir"])
    with pytest.raises(ValueError):
        FileRoots([str(tmp_path / "missing")])
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(ValueError):
        FileRoots([str(tmp_path / "f.txt")])


def test_resolve_accepts_supported_file(root: Path) -> None:
    (root / "a.txt").write_text("hello")
    assert FileRoots([str(root)]).resolve_inside(str(root / "a.txt")) == (root / "a.txt").resolve()


def test_traversal_and_outside_paths_are_refused(tmp_path: Path, root: Path) -> None:
    (tmp_path / "secret.txt").write_text("s")
    roots = FileRoots([str(root)])
    with pytest.raises(FileAccessDenied):
        roots.resolve_inside(str(root / ".." / "secret.txt"))
    with pytest.raises(FileAccessDenied):
        roots.resolve_inside(str(tmp_path / "secret.txt"))
    with pytest.raises(FileAccessDenied):
        roots.resolve_inside(str(root / "missing.txt"))
    sibling = tmp_path / "docs-evil"
    sibling.mkdir()
    (sibling / "x.txt").write_text("x")
    with pytest.raises(FileAccessDenied):
        roots.resolve_inside(str(sibling / "x.txt"))


def test_symlink_pointing_outside_is_refused(tmp_path: Path, root: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported")
    with pytest.raises(FileAccessDenied):
        FileRoots([str(root)]).resolve_inside(str(link))


def test_hidden_unsupported_directory_and_oversized_are_refused(root: Path) -> None:
    roots = FileRoots([str(root)])
    (root / ".git").mkdir()
    (root / ".git" / "a.txt").write_text("x")
    (root / ".hidden.txt").write_text("x")
    (root / "run.exe").write_bytes(b"x")
    (root / "sub").mkdir()
    big = root / "big.txt"
    with big.open("wb") as handle:
        handle.truncate(MAX_FILE_BYTES + 1)
    for target in (
        root / ".git" / "a.txt",
        root / ".hidden.txt",
        root / "run.exe",
        root / "sub",
        big,
    ):
        with pytest.raises(FileAccessDenied):
            roots.resolve_inside(str(target))


def test_walk_skips_hidden_unsupported_symlinks_and_oversized(tmp_path: Path, root: Path) -> None:
    (root / "keep.txt").write_text("k")
    (root / "nested").mkdir()
    (root / "nested" / "deep.md").write_text("d")
    (root / ".secret").mkdir()
    (root / ".secret" / "no.txt").write_text("n")
    (root / "skip.exe").write_bytes(b"x")
    with (root / "huge.txt").open("wb") as handle:
        handle.truncate(MAX_FILE_BYTES + 1)
    outside = tmp_path / "out.txt"
    outside.write_text("o")
    with contextlib.suppress(OSError, NotImplementedError):
        (root / "ln.txt").symlink_to(outside)
    found = {p.name for p in FileRoots([str(root)]).walk()}
    assert found == {"keep.txt", "deep.md"}


def test_walk_is_capped(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files_module, "MAX_WALKED_FILES", 2)
    for i in range(5):
        (root / f"f{i}.txt").write_text("x")
    assert len(list(FileRoots([str(root)]).walk())) == 2


def test_index_search_semantics(tmp_path: Path, root: Path) -> None:
    index, _, _ = _index(tmp_path, root)
    (root / "a.txt").write_text("Quarterly budget review for zanzibar")
    (root / "b.md").write_text("budget only")
    assert index.refresh() == (2, 0)
    assert {h.name for h in index.search("budget", 10)} == {"a.txt", "b.md"}
    assert [h.name for h in index.search("BUDGET Zanzibar", 10)] == ["a.txt"]
    assert index.search("budget missingword", 10) == []
    assert index.search("!", 10) == []
    hit = index.search("zanzibar", 10)[0]
    assert Path(hit.path) == (root / "a.txt").resolve()
    assert hit.size == len("Quarterly budget review for zanzibar")
    assert len(index.search("budget", 1)) == 1


def test_unchanged_files_are_not_reextracted_and_changes_reindex(
    tmp_path: Path, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, _, _ = _index(tmp_path, root)
    target = root / "a.txt"
    target.write_text("alpha words")
    calls: list[str] = []
    real = files_module.extract_text

    def counting(data: bytes, suffix: str) -> str:
        calls.append(suffix)
        return real(data, suffix)

    monkeypatch.setattr(files_module, "extract_text", counting)
    assert index.refresh() == (1, 0)
    assert index.refresh() == (0, 0)
    assert len(calls) == 1
    target.write_text("beta words longer")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert index.refresh() == (1, 0)
    assert len(calls) == 2
    assert index.search("alpha", 5) == []
    assert [h.name for h in index.search("beta", 5)] == ["a.txt"]


def test_deleted_files_are_removed(tmp_path: Path, root: Path) -> None:
    index, db, _ = _index(tmp_path, root)
    (root / "a.txt").write_text("gone soon")
    (root / "b.txt").write_text("stays here")
    index.refresh()
    (root / "a.txt").unlink()
    assert index.refresh() == (0, 1)
    assert index.search("gone", 5) == []
    assert db.query("SELECT COUNT(*) AS n FROM local_files")[0]["n"] == 1
    assert db.query("SELECT COUNT(*) AS n FROM local_files_fts")[0]["n"] == 1


def test_search_drops_hit_whose_file_was_deleted(tmp_path: Path, root: Path) -> None:
    index, _, _ = _index(tmp_path, root)
    (root / "a.txt").write_text("ephemeral content")
    index.refresh()
    (root / "a.txt").unlink()
    assert index.search("ephemeral", 5) == []


def test_database_files_hold_no_plaintext_words_or_paths(tmp_path: Path, root: Path) -> None:
    index, db, _ = _index(tmp_path, root)
    (root / "quokkaplan.txt").write_text("the zygomorphic marmoset budget")
    (root / "sub").mkdir()
    (root / "sub" / "wombatnotes.md").write_text("zygomorphic marmoset again")
    index.refresh()
    assert len(index.search("zygomorphic", 5)) == 2
    state = tmp_path / "state"
    blobs = b"".join(p.read_bytes() for p in state.iterdir() if p.name.startswith("agent.db"))
    assert len(blobs) > 0
    wal = state / "agent.db-wal"
    assert wal.exists()
    for needle in (b"zygomorphic", b"marmoset", b"quokkaplan", b"wombatnotes"):
        assert needle not in blobs
    assert str(root).encode() not in blobs
    db.close()
