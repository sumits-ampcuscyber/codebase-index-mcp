"""Print the MCP config block with correct absolute paths, ready to paste.

  python print_mcp_config.py            # JSON for Antigravity / Codex / any mcpServers-style config
  python print_mcp_config.py --cursor   # same JSON, for .cursor/mcp.json (or use setup_cursor.py)
  python print_mcp_config.py --claude   # a `claude mcp add ...` command for Claude Code
  python print_mcp_config.py --name codebase-index-myapp   # use a unique name per repo
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=None)
    ap.add_argument("--cursor", action="store_true")
    ap.add_argument("--claude", action="store_true")
    a = ap.parse_args()
    name = a.name or f"codebase-index-{config.REPO_ROOT.name}".lower().replace(" ", "-")
    server = str(Path(__file__).resolve().parent / "mcp_server.py")
    if a.claude:
        cmd = ["claude", "mcp", "add", name, "--scope", "project", "-e", f"CODEBASE_ROOT={config.REPO_ROOT}",
               "--", sys.executable, server]
        print(subprocess.list2cmdline(cmd) if sys.platform == "win32" else " ".join(
            f"'{c}'" if " " in c else c for c in cmd))
        print(f"\n# Run it from the repo root: {config.REPO_ROOT}", file=sys.stderr)
        print("# --scope project writes .mcp.json in the repo (shared with the team); drop it for a "
              "personal (local) server.", file=sys.stderr)
        return
    block = {"mcpServers": {name: {
        "command": sys.executable,
        "args": [server],
        "env": {"CODEBASE_ROOT": str(config.REPO_ROOT)},
    }}}
    print(json.dumps(block, indent=2))
    print("\n# Repo being indexed:", config.REPO_ROOT, file=sys.stderr)
    if a.cursor:
        print("# Save as: <repo>/.cursor/mcp.json (or merge). Easier: python setup_cursor.py", file=sys.stderr)
    else:
        print("# Paste into your client's MCP config, e.g. ~/.gemini/antigravity/mcp_config.json (merge inside "
              'the existing "mcpServers" object if it already has other servers)', file=sys.stderr)


if __name__ == "__main__":
    main()
