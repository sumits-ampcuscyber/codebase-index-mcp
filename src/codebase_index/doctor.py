"""`codebase-index doctor`: check the install, the repo and the client wiring, and say what to fix."""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import __version__, config

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def _client_files() -> list[tuple[str, Path, str]]:
    r = config.REPO_ROOT
    return [("Cursor", r / ".cursor" / "mcp.json", "mcpServers"),
            ("Claude Code / VS Code Copilot", r / ".mcp.json", "mcpServers"),
            ("VS Code (legacy)", r / ".vscode" / "mcp.json", "servers"),
            ("Antigravity", r / ".agents" / "mcp_config.json", "mcpServers")]


def _codex_configs(root: Path) -> list[tuple[str, str | None]]:
    """Find codebase-index entries without importing a TOML dependency on Python 3.10."""
    candidates = [("Codex project", root / ".codex" / "config.toml"),
                  ("Codex user", Path.home() / ".codex" / "config.toml")]
    found: list[tuple[str, str | None]] = []
    section = re.compile(r"(?ms)^\[mcp_servers\.([A-Za-z0-9_-]+)\]\s*(.*?)(?=^\[|\Z)")
    for label, path in candidates:
        try:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError:
            continue
        for match in section.finditer(text):
            body = match.group(2)
            if "codebase_index.server" not in body and "codebase-index-mcp" not in body:
                continue
            command = re.search(r"(?m)^command\s*=\s*[\"']([^\"']+)[\"']", body)
            found.append((f"{label} '{match.group(1)}'", command.group(1) if command else None))
    return found


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
                     ("tree_sitter_typescript", "tree-sitter-typescript"),
                     ("tree_sitter_yaml", "tree-sitter-yaml")):
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001 - report any import problem
            say(FAIL, f"cannot import {mod} ({e.__class__.__name__}); pip install '{pip}' in {sys.executable}")
    git = config.git_exe()
    if git:
        say(OK, f"git found ({git})")
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
            say(WARN, "index is empty: no supported files (.py .js .jsx .ts .tsx .yaml .yml tsconfig*.json) found, or all git-ignored")
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
        if not isinstance(servers, dict):
            say(FAIL, f"{label}: {path} must contain a '{key}' object")
            continue
        for name, ent in servers.items():
            if not isinstance(ent, dict):
                continue
            blob = json.dumps(ent)
            if "codebase_index" not in blob and "mcp_server" not in blob:
                continue
            found += 1
            cmd = ent.get("command", "")
            ok = isinstance(cmd, str) and bool(cmd) and (Path(cmd).exists() or shutil.which(cmd))
            shown = cmd if isinstance(cmd, str) else repr(cmd)
            say(OK if ok else FAIL, f"{label}: server '{name}' -> {shown}" +
                ("" if ok else "  (command not found)"))

    codex_found = _codex_configs(root)
    for label, cmd in codex_found:
        found += 1
        ok = bool(cmd) and (Path(cmd).exists() or shutil.which(cmd))
        say(OK if ok else FAIL, f"{label} -> {cmd or '(no command found)'}" +
            ("" if ok else "  (command not found)"))
    try:
        agents_has_index_rule = "codebase-index:start" in (root / "AGENTS.md").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        agents_has_index_rule = False
    if agents_has_index_rule and not codex_found and not (root / ".agents" / "mcp_config.json").is_file():
        say(WARN, "Codex: AGENTS.md instructions found, but no registered MCP server; run `codebase-index setup codex --codex-scope project`")
    if not found:
        say(WARN, "no client config in this repo: run `codebase-index setup <cursor|claude-code|vscode|codex|antigravity>`")

    keys = [k for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(k)]
    say(OK, f"summarize_file enabled via {keys[0]}" if keys else
        "summarize_file disabled (no API key): every other tool works, fully offline")
    print("\nAll good." if not bad else f"\n{bad} problem(s) found.")
    return 1 if bad else 0
