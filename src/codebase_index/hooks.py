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
import tempfile
import time
from pathlib import Path

from . import config, safefs

HOOKS = ("post-commit", "post-checkout", "post-merge", "post-rewrite")
START = "# >>> codebase-index-mcp >>>"
END = "# <<< codebase-index-mcp <<<"
LOCK = "hook-refresh.lock"
LOCK_STALE = 600  # seconds; an older lock is left over from a crashed run


def _git_value(*args: str) -> str:
    git = config.git_exe()
    if git is None:
        sys.exit("git not found on PATH")
    kwargs = {"capture_output": True, "text": True, "timeout": 10}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000
    out = subprocess.run([git, *config.GIT_SAFE_ARGS, "-C", str(config.REPO_ROOT),
                          "rev-parse", *args], **kwargs)
    if out.returncode != 0:
        sys.exit(f"Not a git repository: {config.REPO_ROOT}\n{out.stderr.strip()}")
    return out.stdout.strip()


def _has_link(path: Path) -> bool:
    """Return true when an existing component is a symlink or Windows reparse link."""
    current = path
    while True:
        try:
            if safefs._is_link(os.lstat(current)):
                return True
        except FileNotFoundError:
            pass
        except OSError:
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _safe_hooks_path() -> Path:
    """Resolve Git's hooks path, allowing only the repository or its Git metadata directory."""
    repo = config.REPO_ROOT.resolve()
    git_dir = Path(_git_value("--git-dir"))
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    git_dir = git_dir.resolve()
    raw = Path(_git_value("--git-path", "hooks"))
    path = raw if raw.is_absolute() else repo / raw
    if _has_link(path):
        sys.exit(f"refusing Git hooks path through a symlink or junction: {path}")
    resolved = path.resolve()
    if not (resolved.is_relative_to(repo) or resolved.is_relative_to(git_dir)):
        sys.exit(f"refusing Git hooks path outside the repository/Git directory: {resolved}")
    return resolved


def hooks_dir() -> Path:
    return _safe_hooks_path()


def _safe_hook_file(directory: Path, name: str) -> Path:
    path = directory / name
    if path.parent != directory or _has_link(path):
        sys.exit(f"refusing unsafe Git hook path: {path}")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return path
    if not stat.S_ISREG(st.st_mode):
        sys.exit(f"refusing non-regular Git hook path: {path}")
    return path


def _atomic_write(path: Path, text: str, mode: int) -> None:
    """Replace a hook without following a swapped-in symlink."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        if _has_link(path.parent):
            sys.exit(f"refusing Git hooks directory changed to a symlink or junction: {path.parent}")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


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
    if _has_link(d):
        sys.exit(f"refusing Git hooks directory through a symlink or junction: {d}")
    for name in HOOKS:
        path = _safe_hook_file(d, name)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        cleaned = strip_block(existing)
        if uninstall:
            if existing and cleaned.strip() in ("", "#!/bin/sh"):
                path.unlink()
            elif existing:
                _atomic_write(path, cleaned, stat.S_IMODE(path.stat().st_mode))
            print(f"removed from {path}")
            continue
        if not cleaned.strip():
            cleaned = "#!/bin/sh\n"
        elif not cleaned.endswith("\n"):
            cleaned += "\n"
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        _atomic_write(path, cleaned + block(), mode)
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
