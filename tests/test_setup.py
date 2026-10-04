"""Tests for the client setup, instruction templates and CLI wiring (no index needed)."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from codebase_index import clients, server
from codebase_index.cli import build_parser


def args(client, ws, **kw):
    d = dict(client=client, workspace=str(ws), name="codebase-index-demo", model=None,
             no_subagent=False, dry_run=False)
    d.update(kw)
    return argparse.Namespace(**d)


def run_setup(a):
    with contextlib.redirect_stdout(io.StringIO()):
        clients.run_setup(a)


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cursor_merges_and_is_idempotent(self):
        (self.ws / ".cursor").mkdir()
        (self.ws / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        run_setup(args("cursor", self.ws, model="my-model"))
        first = (self.ws / ".cursor" / "mcp.json").read_text()
        servers = json.loads(first)["mcpServers"]
        self.assertEqual(set(servers), {"other", "codebase-index-demo"})
        self.assertEqual(servers["codebase-index-demo"]["args"], ["-m", "codebase_index.server"])
        self.assertIn("model: my-model", (self.ws / ".cursor/agents/codebase-explorer.md").read_text())
        run_setup(args("cursor", self.ws, model="my-model"))
        self.assertEqual(first, (self.ws / ".cursor" / "mcp.json").read_text())

    def test_cursor_no_subagent(self):
        run_setup(args("cursor", self.ws, no_subagent=True))
        self.assertFalse((self.ws / ".cursor/agents").exists())
        self.assertNotIn("codebase-explorer", (self.ws / ".cursor/rules/codebase-index.mdc").read_text())

    def test_claude_code_files(self):
        (self.ws / "CLAUDE.md").write_text("# Mine\n\nkeep me\n")
        run_setup(args("claude-code", self.ws))
        run_setup(args("claude-code", self.ws))
        md = (self.ws / "CLAUDE.md").read_text()
        self.assertIn("keep me", md)
        self.assertEqual(md.count(clients.MD_START), 1)
        ent = json.loads((self.ws / ".mcp.json").read_text())["mcpServers"]["codebase-index-demo"]
        self.assertEqual(ent["type"], "stdio")
        agent = (self.ws / ".claude/agents/codebase-explorer.md").read_text()
        self.assertIn("model: haiku", agent)
        self.assertNotIn("{{MODEL}}", agent)

    def test_vscode_uses_servers_key(self):
        run_setup(args("vscode", self.ws))
        data = json.loads((self.ws / ".vscode" / "mcp.json").read_text())
        self.assertIn("codebase-index-demo", data["servers"])
        self.assertNotIn("mcpServers", data)
        self.assertTrue((self.ws / ".github" / "copilot-instructions.md").exists())

    def test_codex_writes_agents_md_only(self):
        run_setup(args("codex", self.ws))
        self.assertTrue((self.ws / "AGENTS.md").exists())
        self.assertFalse((self.ws / ".mcp.json").exists())

    def test_dry_run_writes_nothing(self):
        run_setup(args("all", self.ws, dry_run=True))
        self.assertEqual(list(self.ws.iterdir()), [])


class TemplateTest(unittest.TestCase):
    def test_instructions_mention_every_core_tool(self):
        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        text = clients.template("instructions.md") + clients.template("cursor-rule.mdc")
        for name in names - {"reindex", "index_stats"}:
            self.assertIn(f"`{name}`", text, f"{name} missing from the rule templates")

    def test_cli_parses_every_command(self):
        p = build_parser()
        for argv in (["index"], ["stats"], ["map"], ["search", "x"], ["setup", "cursor"], ["doctor"],
                     ["bench"], ["hooks", "--uninstall"], ["config"], ["callers", "f", "--depth", "2"]):
            p.parse_args(argv)


if __name__ == "__main__":
    unittest.main()
