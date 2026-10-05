from __future__ import annotations

import base64
import sys
from datetime import UTC, datetime
from pathlib import Path

import keyring
import pytest

import agent.main as main_module
from agent.main import main
from agent.store.backup import BackupError, create_backup, restore_backup
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from tests.conftest import InMemoryKeyring

PASSPHRASE = "correct horse battery"
FAST = 2**14
ROW_VALUE = "synthetic-row-subject-ZX81"
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _clock() -> datetime:
    return NOW


def _make_db(path: Path, keystore: KeyStore) -> bytes:
    db_key = keystore.get_or_create_bytes("db_key")
    cipher = FieldCipher(db_key)
    db = Database(path)
    db.execute(
        "INSERT INTO conversations (id, created_at, redaction_map_enc) VALUES (?, ?, ?)",
        ("conv-1", "2026-10-01T00:00:00+00:00", cipher.encrypt(ROW_VALUE, "conv-1")),
    )
    db.close()
    return db_key


def _backup(db: Path, out: Path, passphrase: str = PASSPHRASE) -> None:
    create_backup(db, out, passphrase, KeyStore(), _clock, scrypt_n=FAST)


@pytest.fixture
def backup_file(tmp_path: Path) -> Path:
    _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)
    return out


def _new_machine() -> None:
    keyring.set_keyring(InMemoryKeyring())


def test_round_trip_on_new_machine(tmp_path: Path) -> None:
    db_key = _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)

    _new_machine()
    target = tmp_path / "new" / "agent.db"
    restore_backup(out, target, PASSPHRASE, KeyStore(), force=False)

    assert KeyStore().get_bytes("db_key") == db_key
    db = Database(target)
    blob = db.query("SELECT redaction_map_enc FROM conversations WHERE id='conv-1'")[0][0]
    db.close()
    assert FieldCipher(db_key).decrypt_str(blob, "conv-1") == ROW_VALUE


def test_backup_contains_no_plaintext_or_raw_key(tmp_path: Path) -> None:
    db_key = _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)
    data = out.read_bytes()
    assert ROW_VALUE.encode() not in data
    assert db_key not in data
    assert base64.b64encode(db_key) not in data
    assert base64.urlsafe_b64encode(db_key) not in data
    assert b"CREATE TABLE" not in data


def test_backup_carries_only_db_key(tmp_path: Path) -> None:
    store = KeyStore()
    _make_db(tmp_path / "agent.db", store)
    store.set("other_entry", "synthetic other entry")
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)
    _new_machine()
    restore_backup(out, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=False)
    assert KeyStore().get("other_entry") is None


def test_wrong_passphrase(backup_file: Path, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="wrong passphrase or file is corrupted"):
        restore_backup(
            backup_file, tmp_path / "r.db", "another passphrase!", KeyStore(), force=True
        )
    assert not (tmp_path / "r.db").exists()


def _flip(path: Path, offset: int) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0x01
    path.write_bytes(bytes(data))


def test_tampered_header_value_fails_authentication(backup_file: Path, tmp_path: Path) -> None:
    data = backup_file.read_bytes()
    # Change created_at digits: still valid JSON, so only the AAD binding catches it.
    tampered = data.replace(b"2026-10-05", b"2026-10-06", 1)
    assert tampered != data
    backup_file.write_bytes(tampered)
    with pytest.raises(BackupError, match="wrong passphrase or file is corrupted"):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_tampered_header_byte_rejected(backup_file: Path, tmp_path: Path) -> None:
    _flip(backup_file, 8 + 3)
    with pytest.raises(BackupError):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_tampered_ciphertext(backup_file: Path, tmp_path: Path) -> None:
    _flip(backup_file, len(backup_file.read_bytes()) - 40)
    with pytest.raises(BackupError, match="wrong passphrase or file is corrupted"):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


@pytest.mark.parametrize("keep", [0, 4, 8, 60, 200])
def test_truncated_file(backup_file: Path, tmp_path: Path, keep: int) -> None:
    backup_file.write_bytes(backup_file.read_bytes()[:keep])
    with pytest.raises(BackupError):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_truncated_ciphertext(backup_file: Path, tmp_path: Path) -> None:
    backup_file.write_bytes(backup_file.read_bytes()[:-100])
    with pytest.raises(BackupError, match="wrong passphrase or file is corrupted"):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_wrong_magic(backup_file: Path, tmp_path: Path) -> None:
    backup_file.write_bytes(b"NOTABAK\n" + backup_file.read_bytes()[8:])
    with pytest.raises(BackupError, match="not a valid"):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("n", 2**10),
        ("n", 2**21),
        ("n", 3 * 2**14),
        ("r", 16),
        ("p", 2),
        ("v", 2),
        ("kdf", "pbkdf2"),
    ],
)
def test_unsafe_header_params_rejected(
    backup_file: Path, tmp_path: Path, field: str, value: object
) -> None:
    import json

    data = backup_file.read_bytes()
    end = data.index(b"\n", 8)
    header = json.loads(data[8:end])
    header[field] = value
    backup_file.write_bytes(
        data[:8] + json.dumps(header, separators=(",", ":")).encode() + data[end:]
    )
    with pytest.raises(BackupError, match="unsupported backup format"):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_refuses_to_overwrite_output(tmp_path: Path) -> None:
    _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "agent.bak"
    out.write_bytes(b"precious")
    with pytest.raises(BackupError, match="overwrite"):
        _backup(tmp_path / "agent.db", out)
    assert out.read_bytes() == b"precious"


def test_short_passphrase_rejected(tmp_path: Path) -> None:
    _make_db(tmp_path / "agent.db", KeyStore())
    with pytest.raises(BackupError, match="at least 12"):
        _backup(tmp_path / "agent.db", tmp_path / "agent.bak", "short")
    assert not (tmp_path / "agent.bak").exists()


def test_backup_without_db_key_refused(tmp_path: Path) -> None:
    Database(tmp_path / "agent.db").close()
    with pytest.raises(BackupError, match="db_key"):
        _backup(tmp_path / "agent.db", tmp_path / "agent.bak")


def test_backup_missing_database_refused(tmp_path: Path) -> None:
    KeyStore().get_or_create_bytes("db_key")
    with pytest.raises(BackupError, match="not found"):
        _backup(tmp_path / "missing.db", tmp_path / "agent.bak")
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_backup_file_permissions(backup_file: Path) -> None:
    assert backup_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_restored_db_permissions(backup_file: Path, tmp_path: Path) -> None:
    _new_machine()
    target = tmp_path / "r.db"
    restore_backup(backup_file, target, PASSPHRASE, KeyStore(), force=False)
    assert target.stat().st_mode & 0o777 == 0o600


def test_no_temp_files_left(backup_file: Path) -> None:
    assert not list(backup_file.parent.glob("*.tmp"))


def test_restore_refuses_existing_db_without_force(backup_file: Path, tmp_path: Path) -> None:
    existing = tmp_path / "agent.db"
    before = existing.read_bytes()
    with pytest.raises(BackupError, match="already exists"):
        restore_backup(backup_file, existing, PASSPHRASE, KeyStore(), force=False)
    assert existing.read_bytes() == before


def test_restore_refuses_mismatched_db_key_without_force(backup_file: Path, tmp_path: Path) -> None:
    _new_machine()
    other = KeyStore().get_or_create_bytes("db_key")
    with pytest.raises(BackupError, match="different db_key"):
        restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=False)
    assert KeyStore().get_bytes("db_key") == other
    assert not (tmp_path / "r.db").exists()


def test_force_moves_old_db_aside(backup_file: Path, tmp_path: Path) -> None:
    target = tmp_path / "agent.db"
    (tmp_path / "agent.db-wal").write_bytes(b"wal")
    old = target.read_bytes()
    restore_backup(backup_file, target, PASSPHRASE, KeyStore(), force=True, now=_clock)
    aside = tmp_path / "agent.db.pre-restore-20261005T120000Z"
    assert aside.read_bytes() == old
    assert (tmp_path / "agent.db.pre-restore-20261005T120000Z-wal").read_bytes() == b"wal"
    assert not (tmp_path / "agent.db-wal").exists()
    Database(target).close()


def test_force_keeps_the_replaced_db_key(backup_file: Path, tmp_path: Path) -> None:
    backup_key = KeyStore().get_bytes("db_key")
    _new_machine()
    other = KeyStore().get_or_create_bytes("db_key")
    restore_backup(backup_file, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True, now=_clock)
    assert KeyStore().get_bytes("db_key") == backup_key
    assert KeyStore().get_bytes("db_key.pre-restore-20261005T120000Z") == other


def test_restore_rejects_newer_schema(tmp_path: Path) -> None:
    import sqlite3

    _make_db(tmp_path / "agent.db", KeyStore())
    conn = sqlite3.connect(tmp_path / "agent.db")
    conn.execute("PRAGMA user_version=999")
    conn.close()
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)
    with pytest.raises(BackupError, match="schema version"):
        restore_backup(out, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_restore_rejects_non_sqlite_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent.store.backup as backup_module

    _make_db(tmp_path / "agent.db", KeyStore())
    monkeypatch.setattr(backup_module, "_snapshot", lambda _p: b"this is not sqlite" * 100)
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)
    with pytest.raises(BackupError, match="valid database"):
        restore_backup(out, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=True)


def test_backup_of_wal_db_in_use(tmp_path: Path) -> None:
    keystore = KeyStore()
    _make_db(tmp_path / "agent.db", keystore)
    live = Database(tmp_path / "agent.db")
    live.execute(
        "INSERT INTO conversations (id, created_at) VALUES ('conv-2', '2026-10-02T00:00:00+00:00')"
    )
    out = tmp_path / "agent.bak"
    _backup(tmp_path / "agent.db", out)
    live.close()
    _new_machine()
    restore_backup(out, tmp_path / "r.db", PASSPHRASE, KeyStore(), force=False)
    restored = Database(tmp_path / "r.db")
    ids = {r[0] for r in restored.query("SELECT id FROM conversations")}
    restored.close()
    assert ids == {"conv-1", "conv-2"}


# CLI ---------------------------------------------------------------------------------------


class Prompts:
    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self._answers.pop(0)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setattr(main_module, "assert_secure_backend", lambda: None)
    real = main_module.create_backup
    monkeypatch.setattr(
        main_module,
        "create_backup",
        lambda *a, **k: real(*a, **k, scrypt_n=FAST),
    )
    return monkeypatch


def test_cli_backup_and_restore(
    cli: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_key = _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "cli.bak"
    prompts = Prompts(PASSPHRASE, PASSPHRASE)
    assert main(["backup", "--out", str(out)], read_passphrase=prompts) == 0
    assert len(prompts.asked) == 2
    stdout = capsys.readouterr().out
    assert str(out) in stdout
    assert PASSPHRASE not in stdout

    _new_machine()
    cli.setenv("PERSONALAI_DB_PATH", str(tmp_path / "restored.db"))
    assert main(["restore", "--in", str(out)], read_passphrase=Prompts(PASSPHRASE)) == 0
    assert (tmp_path / "restored.db").exists()
    assert KeyStore().get_bytes("db_key") == db_key


def test_cli_backup_passphrase_mismatch(cli: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "cli.bak"
    code = main(
        ["backup", "--out", str(out)],
        read_passphrase=Prompts(PASSPHRASE, PASSPHRASE + "x"),
    )
    assert code == 2
    assert not out.exists()


def test_cli_backup_short_passphrase_exit_2(cli: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _make_db(tmp_path / "agent.db", KeyStore())
    out = tmp_path / "cli.bak"
    assert main(["backup", "--out", str(out)], read_passphrase=Prompts("short", "short")) == 2
    assert not out.exists()


def test_cli_restore_wrong_passphrase_exit_2(
    cli: pytest.MonkeyPatch, tmp_path: Path, backup_file: Path
) -> None:
    cli.setenv("PERSONALAI_DB_PATH", str(tmp_path / "r.db"))
    assert (
        main(["restore", "--in", str(backup_file)], read_passphrase=Prompts("wrong one 123")) == 2
    )


def test_cli_restore_existing_db_needs_force(
    cli: pytest.MonkeyPatch, tmp_path: Path, backup_file: Path
) -> None:
    assert main(["restore", "--in", str(backup_file)], read_passphrase=Prompts(PASSPHRASE)) == 2
    assert (
        main(["restore", "--in", str(backup_file), "--force"], read_passphrase=Prompts(PASSPHRASE))
        == 0
    )
    assert list(tmp_path.glob("agent.db.pre-restore-*"))


@pytest.mark.parametrize("argv", [["backup", "--out", "x.bak"], ["restore", "--in", "x.bak"]])
def test_cli_refuses_insecure_keyring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]
) -> None:
    # The autouse in-memory keyring is deliberately not on the allowlist.
    monkeypatch.setenv("PERSONALAI_DB_PATH", str(tmp_path / "agent.db"))

    def must_not_prompt(prompt: str) -> str:
        raise AssertionError("must not prompt under an insecure keyring")

    assert main(argv, read_passphrase=must_not_prompt) == 2
