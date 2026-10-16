"""Wire codebase-index into an agent client: MCP config + a short instruction block.

  codebase-index setup cursor        .cursor/mcp.json, .cursor/rules/codebase-index.mdc, .cursor/agents/...
  codebase-index setup claude-code   .mcp.json, CLAUDE.md block, .claude/agents/codebase-explorer.md
  codebase-index setup vscode        .mcp.json, .github/copilot-instructions.md block
  codebase-index setup codex         AGENTS.md block; prints the command or writes project Codex config
  codebase-index setup antigravity   .agents/mcp_config.json, AGENTS.md block

Config files are merged (other servers are kept) and instruction files are edited between marker lines,
so every command is safe to re-run. Nothing outside the workspace is touched.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config

TEMPLATES = Path(__file__).resolve().parent / "templates"
MD_START = "<!-- codebase-index:start -->"
MD_END = "<!-- codebase-index:end -->"
TOML_START = "# codebase-index:start"
TOML_END = "# codebase-index:end"
CLIENTS = ("cursor", "claude-code", "vscode", "codex", "antigravity")
SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
    def __init__(self, dry: bool, ws: Path, *, codex_scope: str = "command"):
        self.dry = dry
        self.ws = ws.resolve()
        self.codex_scope = codex_scope

    def _check_path(self, path: Path) -> None:
        if not path.resolve().is_relative_to(self.ws):
            sys.exit(f"refusing to access {path}: it resolves outside the workspace (symlink?)")

    def write(self, path: Path, text: str) -> None:
        # A cloned repo may ship .claude/.cursor/... or .mcp.json as symlinks; never follow them out.
        self._check_path(path)
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == text:
            print(f"unchanged   {path}")
            return
        print(f"{'would write' if self.dry else 'wrote      '} {path}")
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write beside the destination and replace it atomically. If a destination is swapped
            # for a symlink after the check above, os.replace replaces that link rather than writing
            # through it; the final check also refuses a swapped parent directory.
            self._check_path(path)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
            temp = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                self._check_path(path)
                os.replace(temp, path)
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass

    def merge_json(self, path: Path, key: str, name: str, entry: dict) -> None:
        self._check_path(path)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError as e:
                sys.exit(f"{path} is not valid JSON ({e}); fix or remove it and run again.")
        if not isinstance(data, dict):
            sys.exit(f"{path} must contain a JSON object at the top level; fix it and run again.")
        servers = data.setdefault(key, {})
        if not isinstance(servers, dict):
            sys.exit(f"{path} must contain a '{key}' JSON object; fix it and run again.")
        servers[name] = entry
        self.write(path, json.dumps(data, indent=2) + "\n")

    def md_block(self, path: Path, body: str) -> None:
        """Insert/replace our block in a Markdown file, leaving everything else untouched."""
        self._check_path(path)
        block = f"{MD_START}\n{body.strip()}\n{MD_END}\n"
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        pat = re.compile(re.escape(MD_START) + r".*?" + re.escape(MD_END) + r"\n?", re.S)
        if pat.search(old):
            new = pat.sub(lambda _m: block, old)
        else:
            new = (old.rstrip() + "\n\n" if old.strip() else "") + block
        self.write(path, new)

    def text_block(self, path: Path, body: str, start: str, end: str, *, conflict: str = "") -> None:
        """Insert/replace a marked text block, preserving all unrelated content."""
        self._check_path(path)
        block = f"{start}\n{body.strip()}\n{end}\n"
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        pat = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\r?\n?", re.S)
        if pat.search(old):
            new = pat.sub(lambda _m: block, old)
        else:
            if conflict and re.search(rf"(?m)^\[{re.escape(conflict)}\]\s*$", old):
                sys.exit(f"{path} already defines [{conflict}] without codebase-index markers; "
                         "remove or rename that table, then run setup again.")
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
    w.merge_json(cur / "mcp.json", "mcpServers", name, server_entry(root, typed=True))
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
    # The workspace-root portable format is now the preferred VS Code/Copilot format and is
    # also understood by Claude Code. This lets a project share one MCP entry across clients.
    portable = ws / ".mcp.json"
    legacy = ws / ".vscode" / "mcp.json"
    if not portable.exists() and legacy.exists():
        # Keep existing VS Code-only setups stable; new setups use the portable format.
        w.merge_json(legacy, "servers", name, server_entry(root, typed=True))
        config_note = "Existing .vscode/mcp.json detected; kept the legacy VS Code format."
    else:
        w.merge_json(portable, "mcpServers", name, server_entry(root))
        config_note = "Portable config: .mcp.json (shared with Claude Code)."
    w.md_block(ws / ".github" / "copilot-instructions.md", template("instructions.md"))
    return ["Trust the workspace, then reload VS Code (or use 'MCP: List Servers').",
            "Use Copilot Chat in Agent mode; enable the server in the tools picker.",
            config_note + " For VS Code-only features such as inputs or sandboxing, "
            "move the entry to .vscode/mcp.json with a top-level 'servers' key."]


def setup_codex(ws: Path, root: Path, name: str, model: str, subagent: bool, w: Writer) -> list[str]:
    del model, subagent
    w.md_block(ws / "AGENTS.md", template("instructions.md"))
    cmd = ["codex", "mcp", "add", name, "--env", f"CODEBASE_ROOT={root}",
           "--", sys.executable, "-m", "codebase_index.server"]
    toml = (f'[mcp_servers.{name}]\ncommand = {json.dumps(sys.executable)}\n'
            f'args = ["-m", "codebase_index.server"]\n'
            f'env = {{ CODEBASE_ROOT = {json.dumps(str(root))} }}')
    scope = w.codex_scope
    if scope == "project":
        w.text_block(ws / ".codex" / "config.toml", toml, TOML_START, TOML_END,
                     conflict=f"mcp_servers.{name}")
        return ["Codex project config written to .codex/config.toml.",
                "Trust the project, restart Codex, then use `/mcp` to verify the server.",
                "The generated block is marked so setup can update it safely on re-run."]
    return ["Codex reads MCP servers from ~/.codex/config.toml or a trusted project's "
            ".codex/config.toml. Run this command to register the server:",
            "  " + _shell_join(cmd),
            "Or add to ~/.codex/config.toml:\n" + "\n".join("  " + ln for ln in toml.splitlines()),
            "For an in-repo, one-command setup use: codebase-index setup codex --codex-scope project"]


def setup_antigravity(ws: Path, root: Path, name: str, model: str, subagent: bool, w: Writer) -> list[str]:
    del model, subagent  # Antigravity has no per-server subagent model
    w.merge_json(ws / ".agents" / "mcp_config.json", "mcpServers", name, server_entry(root))
    w.md_block(ws / "AGENTS.md", template("instructions.md"))
    return ["Antigravity: reload server configurations with `/mcp` in the Antigravity CLI, or press the refresh "
            "button under Installed MCP Servers in the app.",
            "To use it in every project instead, merge the same entry into ~/.gemini/config/mcp_config.json "
            "(run `codebase-index config` to print it)."]


SETUP = {"cursor": setup_cursor, "claude-code": setup_claude_code, "vscode": setup_vscode, "codex": setup_codex,
         "antigravity": setup_antigravity}
DEFAULT_MODEL = {"cursor": None, "claude-code": "haiku", "vscode": "", "codex": "", "antigravity": ""}


def run_setup(args) -> None:
    ws = Path(args.workspace or config.REPO_ROOT).expanduser().resolve()
    # An explicit --workspace is the repo to index, unless CODEBASE_ROOT already says otherwise.
    root = ws if args.workspace and not os.environ.get("CODEBASE_ROOT") else config.REPO_ROOT
    name = args.name or default_name()
    if not SERVER_NAME_RE.fullmatch(name):
        sys.exit("invalid MCP server name: use only letters, numbers, hyphens, or underscores")
    w = Writer(args.dry_run, ws, codex_scope=getattr(args, "codex_scope", "command"))
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
    print("Note: the MCP config files contain absolute paths of this machine (Python and the repo, which "
          "include your user name). Review them before committing to a shared repository.")


def print_config(args) -> None:
    """Generic mcpServers JSON for any other client (Antigravity, Windsurf, Zed, Claude Desktop, ...)."""
    name = args.name or default_name()
    print(json.dumps({"mcpServers": {name: server_entry(config.REPO_ROOT)}}, indent=2))
    print(f"\n# Repo being indexed: {config.REPO_ROOT}\n"
          f"# Merge into the client's MCP config (inside an existing \"mcpServers\" object if present).",
          file=sys.stderr)
