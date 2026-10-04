"""`codebase-index doctor`: check the install, the repo and the client wiring, and say what to fix."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__, config

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def _client_files() -> list[tuple[str, Path, str]]:
    r = config.REPO_ROOT
    return [("Cursor", r / ".cursor" / "mcp.json", "mcpServers"),
            ("Claude Code", r / ".mcp.json", "mcpServers"),
            ("VS Code", r / ".vscode" / "mcp.json", "servers")]


def run() -> int:
    bad = 0

    def say(level: str, msg: str) -> None:
        nonlocal bad
        bad += level == FAIL
        print(f"[{level}] {msg}")

    say(OK, f"codebase-index {__version__}, Python {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        say(FAIL, "Python 3.10+ is required")
    for mod, pip in (("mcp.server.mcpserver", "mcp>=2.2,<3"), ("tree_sitter", "tree-sitter"),
                     ("tree_sitter_python", "tree-sitter-python"),
                     ("tree_sitter_javascript", "tree-sitter-javascript"),
                     ("tree_sitter_typescript", "tree-sitter-typescript")):
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001 - report any import problem
            say(FAIL, f"cannot import {mod} ({e.__class__.__name__}); pip install '{pip}' in {sys.executable}")
    if shutil.which("git"):
        say(OK, "git found")
    else:
        say(WARN, "git not on PATH: falls back to a directory walk, .gitignore is not applied")

    root = config.REPO_ROOT
    say(OK if root.is_dir() else FAIL, f"repo root: {root}")
    if not (root / ".git").exists():
        say(WARN, "root has no .git (set CODEBASE_ROOT if this is the wrong folder)")
    if config.DB_PATH.exists():
        from . import indexer
        con = indexer.db()
        files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        syms = con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        if files:
            say(OK, f"index: {files} files, {syms} symbols ({config.DB_PATH})")
        else:
            say(WARN, "index is empty: no supported files (.py .js .jsx .ts .tsx) found, or all git-ignored")
    else:
        say(WARN, "no index yet: run `codebase-index index` (the MCP server also builds it on start)")

    found = 0
    for label, path, key in _client_files():
        if not path.is_file():
            continue
        try:
            servers = json.loads(path.read_text(encoding="utf-8") or "{}").get(key, {})
        except json.JSONDecodeError:
            say(FAIL, f"{label}: {path} is not valid JSON")
            continue
        for name, ent in servers.items():
            blob = json.dumps(ent)
            if "codebase_index" not in blob and "mcp_server" not in blob:
                continue
            found += 1
            cmd = ent.get("command", "")
            ok = Path(cmd).exists() or shutil.which(cmd)
            say(OK if ok else FAIL, f"{label}: server '{name}' -> {cmd}" + ("" if ok else "  (command not found)"))
    if not found:
        say(WARN, "no client config in this repo: run `codebase-index setup <cursor|claude-code|vscode|codex>`")

    keys = [k for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(k)]
    say(OK, f"summarize_file enabled via {keys[0]}" if keys else
        "summarize_file disabled (no API key): every other tool works, fully offline")
    print("\nAll good." if not bad else f"\n{bad} problem(s) found.")
    return 1 if bad else 0
