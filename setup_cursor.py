"""Wire codebase-index into a Cursor workspace in one step.

Writes (or merges) three files under <workspace>/.cursor/:
  mcp.json                        the MCP server entry (venv python + absolute paths)
  rules/codebase-index.mdc        "use the index before reading files" rule
  agents/codebase-explorer.md     read-only subagent for multi-file questions, pinned to a model

  python setup_cursor.py                         # subagent model = CURSOR_SUBAGENT_MODEL or grok-4.7
  python setup_cursor.py --model <model-id>      # pick another model for the subagent
  python setup_cursor.py --workspace C:/code/app --name codebase-index-app
  python setup_cursor.py --dry-run               # show what would change

Run it with the SAME python you installed the requirements into (the venv python).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent


def _write(path: Path, text: str, dry: bool) -> None:
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        print(f"unchanged  {path}")
        return
    print(f"{'would write' if dry else 'wrote'}  {path}")
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=str(config.REPO_ROOT),
                    help="folder you open in Cursor (default: the indexed repo)")
    ap.add_argument("--model", default=config.CURSOR_SUBAGENT_MODEL,
                    help="model id for the codebase-explorer subagent (default: %(default)s)")
    ap.add_argument("--name", default=None, help="MCP server name (default: codebase-index-<repo>)")
    ap.add_argument("--no-subagent", action="store_true", help="skip .cursor/agents/codebase-explorer.md")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ws = Path(a.workspace).expanduser().resolve()
    cur = ws / ".cursor"
    name = a.name or f"codebase-index-{config.REPO_ROOT.name}".lower().replace(" ", "-")

    mcp_path = cur / "mcp.json"
    data = {}
    if mcp_path.exists():
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            sys.exit(f"{mcp_path} is not valid JSON ({e}); fix or remove it and run again.")
    data.setdefault("mcpServers", {})[name] = {
        "command": sys.executable,
        "args": [str(HERE / "mcp_server.py")],
        "env": {"CODEBASE_ROOT": str(config.REPO_ROOT)},
    }
    _write(mcp_path, json.dumps(data, indent=2) + "\n", a.dry_run)

    rule = (HERE / "rules" / "cursor-codebase-graph.mdc").read_text(encoding="utf-8")
    if a.no_subagent:
        rule = rule.split("## Subagent for multi-file exploration")[0].rstrip() + "\n"
    else:
        rule = rule.replace("Grok 4.7 by default", f"`{a.model}` in this workspace")
    _write(cur / "rules" / "codebase-index.mdc", rule, a.dry_run)

    if not a.no_subagent:
        agent = (HERE / "rules" / "cursor-agents" / "codebase-explorer.md").read_text(encoding="utf-8")
        _write(cur / "agents" / "codebase-explorer.md", agent.replace("{{MODEL}}", a.model), a.dry_run)

    print(f"\nRepo indexed: {config.REPO_ROOT}")
    if not a.no_subagent:
        print(f"Subagent model: {a.model}  (change: python setup_cursor.py --model <id>, or set "
              f"CURSOR_SUBAGENT_MODEL in .env)")
    print("Next: restart Cursor (or toggle the MCP server in Settings > MCP) so the tools appear.")


if __name__ == "__main__":
    main()
