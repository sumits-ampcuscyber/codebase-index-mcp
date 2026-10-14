"""Path-safety and argument-clamp tests on a temporary repo.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

from codebase_index import cheap_delegate  # noqa: E402
from codebase_index import config  # noqa: E402
from codebase_index import indexer  # noqa: E402
from codebase_index import queries  # noqa: E402

FILES = {
    "pkg/__init__.py": "",
    "pkg/util.py": "def check(u):\n    return True\n\n\ndef other():\n    return 1\n",
    ".env": "SECRET=hunter2\n",
    "secret.txt": "SECRET=hunter2\n",
}


class SecurityPathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = (config.REPO_ROOT, config.DB_DIR, config.DB_PATH, config.TOOL_REL, config.WATCH_INTERVAL)
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(cls.tmp.name) / "repo"
        for rel, text in FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        config.REPO_ROOT = root.resolve()
        config.DB_DIR = config.REPO_ROOT / ".codebase-index"
        config.DB_PATH = config.DB_DIR / "index.db"
        config.TOOL_REL = None
        config.WATCH_INTERVAL = 0
        indexer.refresh(full=True)

    @classmethod
    def tearDownClass(cls):
        indexer.close_db()
        (config.REPO_ROOT, config.DB_DIR, config.DB_PATH, config.TOOL_REL, config.WATCH_INTERVAL) = cls.saved
        cls.tmp.cleanup()

    def test_read_symbol_source_refuses_unindexed_file(self):
        out = queries.read_symbol_source(file=".env", line_start=1, line_end=1)
        self.assertNotIn("hunter2", out)
        self.assertTrue(out.startswith("error"), out)

    def test_read_symbol_source_refuses_unindexed_txt(self):
        out = queries.read_symbol_source(file="secret.txt", line_start=1, line_end=1)
        self.assertNotIn("hunter2", out)
        self.assertTrue(out.startswith("error"), out)

    def test_read_symbol_source_line_range_indexed_py(self):
        out = queries.read_symbol_source(file="pkg/util.py", line_start=1, line_end=2)
        self.assertIn("def check(u):", out)
        self.assertIn("return True", out)

    def test_summarize_file_refuses_unindexed_and_skips_network(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}), \
                mock.patch.object(cheap_delegate, "_ask_gemini") as ask:
            out = cheap_delegate.summarize_file(".env", "x")
            self.assertTrue(out.startswith("error"), out)
            self.assertNotIn("hunter2", out)
            ask.assert_not_called()

    def test_negative_limits_do_not_raise(self):
        self.assertIsInstance(queries.find_route("", limit=-1), str)
        self.assertIsInstance(queries.search_symbol("x", limit=-5), str)
        self.assertIsInstance(queries.repo_map(limit=-1), str)
        self.assertIsInstance(queries.find_callers("check", limit=-1), str)
        self.assertIsInstance(queries.find_callees("check", limit=-1), str)
        self.assertIsInstance(queries.who_imports("pkg/util.py", limit=-1), str)

    def test_clamp_helper(self):
        self.assertEqual(queries._lim(-1), 1)
        self.assertEqual(queries._lim(0), 1)
        self.assertEqual(queries._lim(10**9), 500)
        self.assertEqual(queries._lim(30), 30)


if __name__ == "__main__":
    unittest.main()
