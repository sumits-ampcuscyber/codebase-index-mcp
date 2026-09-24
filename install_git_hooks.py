"""Install (or remove) git hooks that refresh the index after commit / checkout / merge / rebase.

Run this with the SAME python you installed the requirements into (the venv python):
  python install_git_hooks.py
  python install_git_hooks.py --uninstall

Existing hooks are preserved: our block is appended between marker lines.
The hook starts a detached refresh so git is not blocked, and so the process is not killed
when the hook shell exits (that happens with a bare "&" on Windows Git Bash).
The MCP server also watches the repo on its own while Cursor is open.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import config

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
    launcher = (Path(__file__).resolve().parent / "refresh_detached.py").as_posix()
    root = config.REPO_ROOT.as_posix()
    return (f'{START}\n'
            f'CODEBASE_ROOT="{root}" "{py}" "{launcher}"\n'
            f'{END}\n')


def strip_block(text: str) -> str:
    return re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    d = hooks_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in HOOKS:
        path = d / name
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        cleaned = strip_block(existing)
        if a.uninstall:
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


if __name__ == "__main__":
    main()
