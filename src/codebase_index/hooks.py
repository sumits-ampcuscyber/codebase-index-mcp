"""Git hooks that refresh the index after commit / checkout / merge / rebase.

The hook starts a detached refresh so git is not blocked, and so the process is not killed when the
hook shell exits (a bare background job dies on Windows Git Bash). Existing hooks are preserved: our
block is appended between marker lines. The MCP server also watches the repo on its own while it runs.
"""
from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import config

HOOKS = ("post-commit", "post-checkout", "post-merge", "post-rewrite")
START = "# >>> codebase-index-mcp >>>"
END = "# <<< codebase-index-mcp <<<"
LOCK = "hook-refresh.lock"
LOCK_STALE = 600  # seconds; an older lock is left over from a crashed run


def hooks_dir() -> Path:
    git = config.git_exe()
    if git is None:
        sys.exit("git not found on PATH")
    out = subprocess.run([git, *config.GIT_SAFE_ARGS, "-C", str(config.REPO_ROOT),
                          "rev-parse", "--git-path", "hooks"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"Not a git repository: {config.REPO_ROOT}\n{out.stderr.strip()}")
    p = Path(out.stdout.strip())
    return p if p.is_absolute() else (config.REPO_ROOT / p)


def block() -> str:
    py = Path(sys.executable).as_posix()
    return (f'{START}\n'
            f'CODEBASE_ROOT={shlex.quote(config.REPO_ROOT.as_posix())} {shlex.quote(py)} '
            f'-m codebase_index refresh-detached\n'
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
    """Called by the hooks: make sure one background refresh runs, and return at once.

    A rebase or a scripted series of commits fires a hook per commit. While a refresh is pending or
    running this only bumps the lock's mtime and the running worker goes round once more, so N commits
    cost one or two index runs instead of N parallel processes fighting over the database."""
    from . import indexer
    try:
        indexer.ensure_db_dir()
    except (OSError, RuntimeError):
        return
    lock = config.DB_DIR / LOCK
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        try:
            m = lock.stat().st_mtime
            now = time.time()
            os.utime(lock, (now, max(now, m + 1)))  # always a visible change, even on 1 s mtime filesystems
        except OSError:
            return
        if now - m < LOCK_STALE:
            return  # the running worker sees the newer mtime and refreshes again
    except OSError:
        return
    env = os.environ.copy()
    env["CODEBASE_ROOT"] = str(config.REPO_ROOT)
    kwargs: dict = {"cwd": str(config.REPO_ROOT), "env": env, "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "codebase_index", "refresh-detached", "--worker"], **kwargs)


def refresh_worker() -> None:
    """Refresh until no hook asked for another run meanwhile, then release the lock."""
    from . import indexer
    lock = config.DB_DIR / LOCK
    try:
        while True:
            try:
                seen = lock.stat().st_mtime
            except OSError:
                seen = None
            indexer.refresh()
            try:
                if lock.stat().st_mtime == seen:
                    break
            except OSError:
                break
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
