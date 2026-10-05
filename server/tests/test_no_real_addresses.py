from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
# Synthetic domains only: example.*, plus the fake attacker domains used in injection tests.
ALLOWED = re.compile(
    r"(?:^|\.)(?:example\.(?:com|org|net|edu)(?:\.au)?|evil\.example|evil\.com)$", re.IGNORECASE
)
SUFFIXES = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".ts", ".tsx", ".txt"}
SKIP = {"uv.lock", "package-lock.json"}


def test_no_address_outside_example_domains_in_tracked_files() -> None:
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    offenders: list[str] = []
    for name in files:
        path = ROOT / name
        if path.suffix not in SUFFIXES or path.name in SKIP or not path.is_file():
            continue
        for match in EMAIL.finditer(path.read_text(encoding="utf-8", errors="replace")):
            if not ALLOWED.search(match.group(1)):
                offenders.append(f"{name}: @{match.group(1)}")
    assert offenders == [], offenders
