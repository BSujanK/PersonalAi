r"""Scheduled-task entry point: ``agent supervise`` with no console anywhere above it.

uv's ``.venv\Scripts\pythonw.exe`` is a console-subsystem launcher, so a task that ran it owned a
console. When that console was closed (it happened during Modern Standby), the launcher exited
with 0xC000013A and took the supervisor and the server with it. The task instead runs the base
interpreter's real GUI-subsystem pythonw.exe as ``pythonw.exe -I -S scripts\agent_task.py``
(see install_task.ps1); this file puts the virtualenv's site-packages on the path and runs the
supervisor.
"""

import site
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
site.addsitedir(str(SERVER_DIR / ".venv" / "Lib" / "site-packages"))

from agent.main import main  # noqa: E402

sys.exit(main(["supervise"]))
