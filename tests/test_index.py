"""End-to-end tests on a small synthetic repo (Python + TS/TSX + Express).

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

from codebase_index import config  # noqa: E402
from codebase_index import indexer  # noqa: E402
from codebase_index import queries  # noqa: E402

FILES = {
    "pkg/__init__.py": "",
    "pkg/models.py": "class User:\n    pass\n",
    "pkg/util.py": "def check(u):\n    return True\n",
    "pkg/service.py": '''\
        """Service module."""
        from .models import User
        from pkg import util
        from fastapi import APIRouter

        router = APIRouter(prefix="/users")
        __all__ = ["UserService", "list_users"]


        class UserService:
            """Manages users."""

            def __init__(self, repo):
                self.repo = repo

            def save(self, user):
                """Persist a user."""
                def _validate(u):
                    return util.check(u)
                _validate(user)
                len(user)
                return self.repo.save(user)


        @router.get("/{user_id}")
        def list_users(user_id: int):
            svc = UserService(None)
            return svc.save(User())


        def _private():
            pass
        ''',
    "web/tsconfig.json": '''\
        {
          // comment with a URL-looking string below
          "$schema": "https://json.schemastore.org/tsconfig",
          "compilerOptions": { "baseUrl": ".", "paths": { "@/*": ["./src/*"] }, },
        }
        ''',
    "web/src/lib/api.ts": '''\
        /** API client helpers. */
        export const api = {
          getUser: async (id: string) => fetchJson(`/u/${id}`),
          save(user: unknown) { return fetchJson("/save"); },
        };
        function fetchJson(url: string) { return fetch(url); }
        export default function () { return 1; }
        ''',
    "web/src/lib/helper.ts": "export function helper() { return 1; }\n",
    "web/src/components/Panel.tsx": '''\
        import { api } from "@/lib/api";
        import { helper } from "../lib/helper";

        // The main panel.
        export const Panel = forwardRef(function Panel(props: any, ref: any) {
          const [a, setA] = useState(0);
          const handleClick = useCallback(() => {
            api.getUser("1");
            helper();
            setA(1);
            setA(2);
            setA(3);
            setA(4);
            setA(5);
          }, []);
          return <div onClick={handleClick}>{a}</div>;
        });
        ''',
    "web/server.js": '''\
        const express = require("express");
        const router = express.Router();
        function healthHandler(req, res) { res.send("ok"); }
        router.get("/health", healthHandler);
        module.exports = router;
        ''',
}


class IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(cls.tmp.name) / "repo"
        for rel, text in FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(text), encoding="utf-8")
        config.REPO_ROOT = root.resolve()
        config.DB_DIR = config.REPO_ROOT / ".codebase-index"
        config.DB_PATH = config.DB_DIR / "index.db"
        config.TOOL_REL = None
        config.WATCH_INTERVAL = 0
        cls.stats = indexer.refresh(full=True)
        cls.con = indexer.db()

    @classmethod
    def tearDownClass(cls):
        indexer.close_db()
        cls.tmp.cleanup()

    def sym(self, name, file_part=""):
        rows = self.con.execute("SELECT * FROM symbols WHERE name=? AND file LIKE ?",
                                (name, f"%{file_part}%")).fetchall()
        self.assertTrue(rows, f"symbol {name} not indexed")
        return rows[0]

    # ---- parser
    def test_all_files_indexed(self):
        self.assertEqual(self.stats["reindexed"], 8)

    def test_nested_symbols(self):
        self.assertEqual(self.sym("_validate")["parent"], "UserService.save")
        self.assertEqual(self.sym("handleClick")["parent"], "Panel")
        self.assertEqual(self.sym("save", "service.py")["kind"], "method")

    def test_object_literal_methods(self):
        self.assertEqual(self.sym("getUser")["parent"], "api")
        self.assertEqual(self.sym("save", "api.ts")["parent"], "api")

    def test_exports(self):
        self.assertEqual(self.sym("UserService")["exported"], 1)
        self.assertEqual(self.sym("router", "service.py")["exported"], 0)  # not in __all__
        self.assertEqual(self.sym("default", "api.ts")["exported"], 1)
        self.assertEqual(self.sym("Panel")["exported"], 1)
        self.assertEqual(self.sym("fetchJson")["exported"], 0)

    def test_docs(self):
        self.assertEqual(self.sym("UserService")["doc"], "Manages users.")
        self.assertEqual(self.sym("save", "service.py")["doc"], "Persist a user.")
        self.assertEqual(self.sym("api")["doc"], "API client helpers.")
        self.assertEqual(self.sym("Panel")["doc"], "The main panel.")

    def test_routes(self):
        rows = {(r["method"], r["path"], r["handler"]) for r in self.con.execute("SELECT * FROM routes")}
        self.assertIn(("GET", "/users/{user_id}", "list_users"), rows)
        self.assertIn(("GET", "/health", "healthHandler"), rows)

    def test_calls_have_receivers_and_skip_builtins(self):
        row = self.con.execute("SELECT * FROM calls WHERE callee='save' AND receiver='repo'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["caller"], "UserService.save")
        self.assertIsNone(self.con.execute("SELECT 1 FROM calls WHERE callee='len'").fetchone())
        self.assertEqual(self.con.execute("SELECT caller FROM calls WHERE callee='helper'").fetchone()[0],
                         "Panel.handleClick")

    def test_import_resolution(self):
        deps = {(r["src"], r["dst"]) for r in self.con.execute("SELECT src, dst FROM deps")}
        self.assertIn(("web/src/components/Panel.tsx", "web/src/lib/api.ts"), deps)      # tsconfig alias
        self.assertIn(("web/src/components/Panel.tsx", "web/src/lib/helper.ts"), deps)   # relative
        self.assertIn(("pkg/service.py", "pkg/models.py"), deps)                        # from .models
        self.assertIn(("pkg/service.py", "pkg/util.py"), deps)                          # from pkg import util

    def test_jsonc(self):
        cfg = indexer._load_jsonc('{"a": "http://x//y", /* c */ "b": [1,], // t\n}')
        self.assertEqual(cfg, {"a": "http://x//y", "b": [1]})

    # ---- queries (text output)
    def test_search(self):
        out = queries.search_symbol("user service")
        self.assertIn("class UserService", out)
        out = queries.search_symbol("UserService.save, getUser")
        self.assertIn("UserService.save(self, user)", out)
        self.assertIn("api.getUser", out)

    def test_summary_depth(self):
        out = queries.get_file_summary("pkg/service.py")
        self.assertIn("GET /users/{user_id} -> list_users", out)
        self.assertNotIn("_validate", out)
        self.assertIn("_validate", queries.get_file_summary("service.py", depth=2))

    def test_callers_and_callees(self):
        out = queries.find_callers("check", depth=2)
        self.assertIn("UserService.save._validate", out)
        out = queries.find_callees("UserService.save")
        self.assertIn("pkg/util.py", out)
        out = queries.find_callees("Panel")
        self.assertIn("helper", out)

    def test_who_imports(self):
        out = queries.who_imports("web/src/lib/api.ts")
        self.assertIn("web/src/components/Panel.tsx", out)

    def test_read_source_and_skeleton(self):
        out = queries.read_symbol_source(symbol="UserService.save")
        self.assertIn("return self.repo.save(user)", out)
        out = queries.read_symbol_source(symbol="Panel", mode="skeleton")
        self.assertIn("folded", out)
        self.assertNotIn("setA(4)", out)
        out = queries.read_symbol_source(file="pkg/util.py", line_start=1, line_end=2)
        self.assertIn("def check", out)

    def test_repo_map_and_routes(self):
        out = queries.repo_map()
        self.assertIn("key files", out)
        self.assertIn("/health", queries.find_route("health"))

    def test_summarize_without_key(self):
        from codebase_index import cheap_delegate
        self.assertIn("needs GEMINI_API_KEY", cheap_delegate.summarize_file("pkg/util.py", "what?"))

    def test_mcp_tools_return_plain_text(self):
        from codebase_index import server as mcp_server
        res = asyncio.run(mcp_server.mcp.call_tool("search_symbol", {"query": "UserService"}))
        self.assertIsNone(getattr(res, "structured_content", None))
        self.assertIn("class UserService", res.content[0].text)
        tools = asyncio.run(mcp_server.mcp.list_tools())
        self.assertEqual({t.name for t in tools}, {
            "repo_map", "search_symbol", "get_file_summary", "get_exports", "read_symbol_source",
            "find_callers", "find_callees", "who_imports", "find_route", "summarize_file", "reindex",
            "index_stats"})


class IncrementalTest(unittest.TestCase):
    def test_change_and_delete(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d).resolve()
            (root / "a.py").write_text("def one():\n    pass\n", encoding="utf-8")
            (root / "b.py").write_text("from a import one\n", encoding="utf-8")
            config.REPO_ROOT, config.TOOL_REL = root, None
            config.DB_DIR = root / ".codebase-index"
            config.DB_PATH = config.DB_DIR / "index.db"
            self.assertEqual(indexer.refresh()["reindexed"], 2)
            self.assertEqual(indexer.refresh()["reindexed"], 0)
            (root / "a.py").write_text("def one():\n    pass\n\ndef two():\n    pass\n", encoding="utf-8")
            self.assertEqual(indexer.refresh()["reindexed"], 1)
            self.assertIn("two", queries.search_symbol("two"))
            (root / "b.py").unlink()
            self.assertEqual(indexer.refresh()["removed"], 1)
            indexer.close_db()


if __name__ == "__main__":
    unittest.main()
