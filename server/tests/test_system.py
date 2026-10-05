"""RealSystem's program lookup, and guards for Windows-only bugs CI on Linux cannot see."""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

import agent.golive.system as system_module
from agent.golive.system import NOT_FOUND, RealSystem

SERVER_DIR = Path(__file__).resolve().parents[1]
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer layout")


def test_program_on_path_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_module.shutil, "which", lambda name: f"/bin/{name}")
    assert RealSystem().which("tailscale") == "/bin/tailscale"


def test_tailscale_is_found_in_its_install_folder_when_not_on_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Tailscale's Windows installer often does not put tailscale.exe on PATH.
    exe = tmp_path / "tailscale.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(system_module.shutil, "which", lambda name: None)
    monkeypatch.setitem(system_module._KNOWN_LOCATIONS, "tailscale", (str(exe),))
    assert RealSystem().which("tailscale") == str(exe)


def test_unknown_program_is_not_found_and_run_reports_127(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_module.shutil, "which", lambda name: None)
    monkeypatch.setitem(system_module._KNOWN_LOCATIONS, "tailscale", ())
    system = RealSystem()
    assert system.which("tailscale") is None
    assert system.which("definitely-not-installed-xyz") is None
    assert system.run(["tailscale", "ip", "-4"]).returncode == NOT_FOUND
    assert system.run(["definitely-not-installed-xyz"]).returncode == NOT_FOUND


@windows_only
def test_default_tailscale_location_expands_program_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "Tailscale"
    folder.mkdir()
    exe = folder / "tailscale.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setattr(system_module.shutil, "which", lambda name: None)
    assert Path(RealSystem().which("tailscale") or "") == exe


# --- text files are always read and written as UTF-8 ----------------------------------------
# Windows' default text encoding is the legacy code page (cp1252), so a bare Path.read_text()
# garbles or rejects non-ASCII content there while passing on Linux.


def _missing_encoding(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        keywords = {k.arg for k in node.keywords}
        if isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
            if "encoding" not in keywords:
                lines.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == "open" and "encoding" not in keywords:
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for k in node.keywords:
                if k.arg == "mode" and isinstance(k.value, ast.Constant):
                    mode = str(k.value.value)
            if "b" not in mode:
                lines.append(node.lineno)
    return lines


def test_guard_spots_missing_encodings() -> None:
    bad = "from pathlib import Path\nPath('a').read_text()\nopen('f')\nopen('f', 'w')\n"
    good = (
        "from pathlib import Path\nPath('a').read_text(encoding='utf-8')\n"
        "open('f', 'rb')\nopen('f', encoding='utf-8')\n"
    )
    assert _missing_encoding(bad) == [2, 3, 4]
    assert _missing_encoding(good) == []


@pytest.mark.parametrize("folder", ["agent", "scripts"])
def test_production_code_names_its_text_encoding(folder: str) -> None:
    offenders = [
        f"{path.relative_to(SERVER_DIR)}:{line}"
        for path in sorted((SERVER_DIR / folder).rglob("*.py"))
        for line in _missing_encoding(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# --- output never crashes on characters the console code page lacks -------------------------


def test_output_streams_survive_unencodable_characters() -> None:
    from agent.main import _tolerate_any_output

    strict = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    with pytest.raises(UnicodeEncodeError):
        strict.write("⟨PHONE_1⟩")  # the placeholder brackets are not in cp1252
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    _tolerate_any_output(stream)
    stream.write("done ✓ ⟨PHONE_1⟩\n")
    stream.flush()
    assert stream.errors == "replace"
