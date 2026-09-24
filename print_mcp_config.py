"""Print the MCP config block with correct absolute paths, ready to paste.

  python print_mcp_config.py            # for Antigravity (mcp_config.json)
  python print_mcp_config.py --cursor   # same JSON, for .cursor/mcp.json
  python print_mcp_config.py --name codebase-index-myapp   # use a unique name per repo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=None)
    ap.add_argument("--cursor", action="store_true")
    a = ap.parse_args()
    name = a.name or f"codebase-index-{config.REPO_ROOT.name}".lower().replace(" ", "-")
    block = {"mcpServers": {name: {
        "command": sys.executable,
        "args": [str(Path(__file__).resolve().parent / "mcp_server.py")],
        "env": {"CODEBASE_ROOT": str(config.REPO_ROOT)},
    }}}
    print(json.dumps(block, indent=2))
    print("\n# Repo being indexed:", config.REPO_ROOT, file=sys.stderr)
    if a.cursor:
        print("# Save as: <repo>/.cursor/mcp.json (or merge into an existing file)", file=sys.stderr)
    else:
        print("# Paste into ~/.gemini/antigravity/mcp_config.json (merge inside the existing "
              '"mcpServers" object if it already has other servers)', file=sys.stderr)


if __name__ == "__main__":
    main()
