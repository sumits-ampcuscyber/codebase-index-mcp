"""Security regressions: repo-controlled git config, symlink escapes, and shell quoting in hooks.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

from codebase_index import config  # noqa: E402
from codebase_index import hooks  # noqa: E402
from codebase_index import indexer  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class _GlobalsMixin:
    """Saves and restores the config globals that these tests patch."""

    def _patch_root(self, root: Path) -> None:
        saved = (config.REPO_ROOT, config.DB_DIR, config.DB_PATH, config.TOOL_REL)
        self.addCleanup(setattr, config, "REPO_ROOT", saved[0])
        self.addCleanup(setattr, config, "DB_DIR", saved[1])
        self.addCleanup(setattr, config, "DB_PATH", saved[2])
        self.addCleanup(setattr, config, "TOOL_REL", saved[3])
        config.REPO_ROOT = root.resolve()
        config.DB_DIR = config.REPO_ROOT / ".codebase-index"
        config.DB_PATH = config.DB_DIR / "index.db"
        config.TOOL_REL = None


class FsmonitorTest(unittest.TestCase):
    def test_repo_config_cannot_run_commands(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d)
            _git(root, "init", "-q")
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            _git(root, "add", "app.py")
            _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
            # Command writes a marker file in the repo when git runs it (sh or cmd compatible).
            py = Path(sys.executable).as_posix()
            _git(root, "config", "core.fsmonitor", f'"{py}" -c "open(\'pwned.txt\',\'w\').write(\'x\')"')
            files = indexer._git_files(root)
            self.assertFalse((root / "pwned.txt").exists())
            self.assertIsNotNone(files)
            self.assertIn("app.py", files)


class SymlinkTest(_GlobalsMixin, unittest.TestCase):
    def test_safe_stat(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as outer, \
                tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d)
            self._patch_root(root)
            (root / "normal.py").write_text("x = 1\n", encoding="utf-8")
            self.assertIsNotNone(indexer._safe_stat(root / "normal.py"))
            self.assertIsNone(indexer._safe_stat(root / "missing.py"))

            secret = Path(outer) / "credentials"
            secret.write_text("secret\n", encoding="utf-8")
            try:
                (root / "link.py").symlink_to(secret)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not permitted here")
            self.assertIsNone(indexer._safe_stat(root / "link.py"))

            # A symlink that stays inside the repo is followed.
            try:
                (root / "inner.py").symlink_to(root / "normal.py")
            except (OSError, NotImplementedError):
                return
            self.assertIsNotNone(indexer._safe_stat(root / "inner.py"))


class HooksQuotingTest(_GlobalsMixin, unittest.TestCase):
    def test_block_quotes_repo_path(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d) / 'evil$(touch x)`y"z'
            self._patch_root(root)
            out = hooks.block()
            self.assertIn(shlex.quote(config.REPO_ROOT.as_posix()), out)
            self.assertIn(shlex.quote(Path(sys.executable).as_posix()), out)
            self.assertNotIn('"$(', out)
            self.assertNotIn('CODEBASE_ROOT="', out)


if __name__ == "__main__":
    unittest.main()
