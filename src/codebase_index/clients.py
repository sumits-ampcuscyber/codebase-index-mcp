"""Wire codebase-index into an agent client: MCP config + a short instruction block.

  codebase-index setup cursor        .cursor/mcp.json, .cursor/rules/codebase-index.mdc, .cursor/agents/...
  codebase-index setup claude-code   .mcp.json, CLAUDE.md block, .claude/agents/codebase-explorer.md
  codebase-index setup vscode        .vscode/mcp.json, .github/copilot-instructions.md block
  codebase-index setup codex         AGENTS.md block; prints the `codex mcp add` command (global config)

Config files are merged (other servers are kept) and instruction files are edited between marker lines,
so every command is safe to re-run. Nothing outside the workspace is touched.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import config

TEMPLATES = Path(__file__).resolve().parent / "templates"
MD_START = "<!-- codebase-index:start -->"
MD_END = "<!-- codebase-index:end -->"
CLIENTS = ("cursor", "claude-code", "vscode", "codex")


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def default_name() -> str:
    repo = config.REPO_ROOT.name.lower().replace(" ", "-").replace("_", "-")
    return repo if repo.startswith("codebase-index") else f"codebase-index-{repo}"


def server_entry(root: Path, *, typed: bool = False) -> dict:
    """MCP stdio entry: this interpreter + `-m codebase_index.server`, so it works for venv, pipx and clones."""
    entry = {
        "command": sys.executable,
        "args": ["-m", "codebase_index.server"],
        "env": {"CODEBASE_ROOT": str(root)},
    }
    return {"type": "stdio", **entry} if typed else entry


class Writer:
    def __init__(self, dry: bool):
        self.dry = dry

    def write(self, path: Path, text: str) -> None:
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == text:
            print(f"unchanged   {path}")
            return
        print(f"{'would write' if self.dry else 'wrote      '} {path}")
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

    def merge_json(self, path: Path, key: str, name: str, entry: dict) -> None:
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError as e:
                sys.exit(f"{path} is not valid JSON ({e}); fix or remove it and run again.")
        data.setdefault(key, {})[name] = entry
        self.write(path, json.dumps(data, indent=2) + "\n")

    def md_block(self, path: Path, body: str) -> None:
        """Insert/replace our block in a Markdown file, leaving everything else untouched."""
        block = f"{MD_START}\n{body.strip()}\n{MD_END}\n"
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        pat = re.compile(re.escape(MD_START) + r".*?" + re.escape(MD_END) + r"\n?", re.S)
        if pat.search(old):
            new = pat.sub(lambda _m: block, old)
        else:
            new = (old.rstrip() + "\n\n" if old.strip() else "") + block
        self.write(path, new)


def _claude_add_command(name: str, root: Path) -> list[str]:
    return ["claude", "mcp", "add", name, "--scope", "project", "-e", f"CODEBASE_ROOT={root}",
            "--", sys.executable, "-m", "codebase_index.server"]


def _shell_join(cmd: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(cmd)
    return " ".join(f"'{c}'" if re.search(r"[^\w@%+=:,./-]", c) else c for c in cmd)


def setup_cursor(ws: Path, root: Path, name: str, model: str, subagent: bool, w: Writer) -> list[str]:
    cur = ws / ".cursor"
    w.merge_json(cur / "mcp.json", "mcpServers", name, server_entry(root))
    rule = template("cursor-rule.mdc")
    if subagent:
        rule = rule.replace("Grok 4.7 by default", f"`{model}` in this workspace")
    else:
        rule = rule.split("## Subagent for multi-file exploration")[0].rstrip()
        rule = rule.replace("; delegate multi-file exploration to the codebase-explorer subagent", "")
        rule = "\n".join(ln for ln in rule.splitlines() if "codebase-explorer" not in ln) + "\n"
    w.write(cur / "rules" / "codebase-index.mdc", rule)
    if subagent:
        w.write(cur / "agents" / "codebase-explorer.md", template("cursor-explorer.md").replace("{{MODEL}}", model))
    return ["Restart Cursor, or toggle the server under Settings > MCP, so the tools appear.",
            f"Subagent model: {model if subagent else '(none)'}  (change: codebase-index setup cursor --model <id>)"]


def setup_claude_code(ws: Path, root: Path, name: str, model: str, subagent: bool, w: Writer) -> list[str]:
    w.merge_json(ws / ".mcp.json", "mcpServers", name, server_entry(root, typed=True))
    w.md_block(ws / "CLAUDE.md", template("instructions.md"))
    if subagent:
        w.write(ws / ".claude" / "agents" / "codebase-explorer.md",
                template("claude-explorer.md").replace("{{MODEL}}", model))
    return ["Start (or restart) `claude` in this folder and approve the project MCP server when asked "
            "(check with `/mcp`).",
            "Prefer the CLI? Equivalent command:  " + _shell_join(_claude_add_command(name, root)),
            f"Subagent model: {model if subagent else '(none)'}  (sonnet | haiku | opus | inherit)"]


def setup_vscode(ws: Path, root: Path, name: str, model: str, subagent: bool, w: Writer) -> list[str]:
    del model, subagent  # VS Code has no per-server subagent model
    w.merge_json(ws / ".vscode" / "mcp.json", "servers", name, server_entry(root, typed=True))
    w.md_block(ws / ".github" / "copilot-instructions.md", template("instructions.md"))
    return ["Open the Command Palette > 'MCP: List Servers' and start the server (or reload the window).",
            "Use Copilot Chat in Agent mode; the tools appear under the tools picker."]


def setup_codex(ws: Path, root: Path, name: str, model: str, subagent: bool, w: Writer) -> list[str]:
    del model, subagent
    w.md_block(ws / "AGENTS.md", template("instructions.md"))
    cmd = ["codex", "mcp", "add", name, "--env", f"CODEBASE_ROOT={root}",
           "--", sys.executable, "-m", "codebase_index.server"]
    toml = (f'[mcp_servers.{name}]\ncommand = {json.dumps(sys.executable)}\n'
            f'args = ["-m", "codebase_index.server"]\n'
            f'env = {{ CODEBASE_ROOT = {json.dumps(str(root))} }}')
    return ["Codex keeps MCP servers in your global ~/.codex/config.toml, so this tool does not edit it. "
            "Run ONE of:",
            "  " + _shell_join(cmd),
            "or add to ~/.codex/config.toml:\n" + "\n".join("  " + ln for ln in toml.splitlines())]


SETUP = {"cursor": setup_cursor, "claude-code": setup_claude_code, "vscode": setup_vscode, "codex": setup_codex}
DEFAULT_MODEL = {"cursor": None, "claude-code": "haiku", "vscode": "", "codex": ""}


def run_setup(args) -> None:
    ws = Path(args.workspace or config.REPO_ROOT).expanduser().resolve()
    # An explicit --workspace is the repo to index, unless CODEBASE_ROOT already says otherwise.
    root = ws if args.workspace and not os.environ.get("CODEBASE_ROOT") else config.REPO_ROOT
    name = args.name or default_name()
    w = Writer(args.dry_run)
    clients = CLIENTS if args.client == "all" else (args.client,)
    for client in clients:
        model = args.model or DEFAULT_MODEL[client] or config.CURSOR_SUBAGENT_MODEL
        print(f"== {client}")
        notes = SETUP[client](ws, root, name, model, not args.no_subagent, w)
        print()
        for n in notes:
            print(n)
        print()
    print(f"Repo indexed: {root}\nBuild the index now (optional, the server also does it): "
          f"codebase-index index")


def print_config(args) -> None:
    """Generic mcpServers JSON for any other client (Antigravity, Windsurf, Zed, Claude Desktop, ...)."""
    name = args.name or default_name()
    print(json.dumps({"mcpServers": {name: server_entry(config.REPO_ROOT)}}, indent=2))
    print(f"\n# Repo being indexed: {config.REPO_ROOT}\n"
          f"# Merge into the client's MCP config (inside an existing \"mcpServers\" object if present).",
          file=sys.stderr)
