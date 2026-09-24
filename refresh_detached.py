"""Start an incremental index refresh and return immediately.

Git hooks call this. The child is detached so it keeps running after the hook
shell exits (a background "&" job is killed on Windows Git Bash).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import config

def main() -> None:
    py = Path(sys.executable)
    cli = Path(__file__).resolve().parent / "cli.py"
    env = os.environ.copy()
    env["CODEBASE_ROOT"] = str(config.REPO_ROOT)
    kwargs: dict = {
        "cwd": str(config.REPO_ROOT),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([str(py), str(cli), "index", "--quiet"], **kwargs)


if __name__ == "__main__":
    main()
