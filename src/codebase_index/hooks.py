"""Git hooks that refresh the index after commit / checkout / merge / rebase.

The hook starts a detached refresh so git is not blocked, and so the process is not killed when the
hook shell exits (a bare background job dies on Windows Git Bash). Existing hooks are preserved: our
block is appended between marker lines. The MCP server also watches the repo on its own while it runs.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from . import config

HOOKS = ("post-commit", "post-checkout", "post-merge", "post-rewrite")
START = "# >>> codebase-index-mcp >>>"
END = "# <<< codebase-index-mcp <<<"


def hooks_dir() -> Path:
    out = subprocess.run(["git", "-C", str(config.REPO_ROOT), "rev-parse", "--git-path", "hooks"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"Not a git repository: {config.REPO_ROOT}\n{out.stderr.strip()}")
    p = Path(out.stdout.strip())
    return p if p.is_absolute() else (config.REPO_ROOT / p)


def block() -> str:
    py = Path(sys.executable).as_posix()
    return (f'{START}\n'
            f'CODEBASE_ROOT="{config.REPO_ROOT.as_posix()}" "{py}" -m codebase_index refresh-detached\n'
            f'{END}\n')


def strip_block(text: str) -> str:
    return re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)


def install(uninstall: bool = False) -> None:
    d = hooks_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in HOOKS:
        path = d / name
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        cleaned = strip_block(existing)
        if uninstall:
            if existing and cleaned.strip() in ("", "#!/bin/sh"):
                path.unlink()
            elif existing:
                path.write_text(cleaned, encoding="utf-8", newline="\n")
            print(f"removed from {path}")
            continue
        if not cleaned.strip():
            cleaned = "#!/bin/sh\n"
        elif not cleaned.endswith("\n"):
            cleaned += "\n"
        path.write_text(cleaned + block(), encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"installed {path}")


def refresh_detached() -> None:
    """Start `codebase-index index --quiet` and return immediately (called by the hooks)."""
    env = os.environ.copy()
    env["CODEBASE_ROOT"] = str(config.REPO_ROOT)
    kwargs: dict = {"cwd": str(config.REPO_ROOT), "env": env, "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "codebase_index", "index", "--quiet"], **kwargs)
