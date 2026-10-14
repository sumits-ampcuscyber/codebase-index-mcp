"""Security regressions for repo-file reads: links in any path component, check/use races, FIFOs, .git/HEAD.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

from codebase_index import config  # noqa: E402
from codebase_index import indexer  # noqa: E402
from codebase_index import queries  # noqa: E402
from codebase_index import safefs  # noqa: E402

SECRET = "hunter2-do-not-leak"


def _file_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        raise unittest.SkipTest("file symlinks are not permitted here (Windows without developer mode)")


def _dir_link(link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows (which needs no special privileges)."""
    if sys.platform == "win32":
        import _winapi
        try:
            _winapi.CreateJunction(str(target), str(link))
            return
        except OSError:
            pass
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        raise unittest.SkipTest("directory links are not permitted here")


class _RepoCase(unittest.TestCase):
    """A fresh temporary repo per test, with config globals patched and restored."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root, self.outside = base / "repo", base / "outside"
        self.root.mkdir()
        self.outside.mkdir()
        saved = (config.REPO_ROOT, config.DB_DIR, config.DB_PATH, config.TOOL_REL)
        self.addCleanup(lambda: (setattr(config, "REPO_ROOT", saved[0]), setattr(config, "DB_DIR", saved[1]),
                                 setattr(config, "DB_PATH", saved[2]), setattr(config, "TOOL_REL", saved[3])))
        self.addCleanup(indexer.close_db)
        config.REPO_ROOT = self.root
        config.DB_DIR = self.root / ".codebase-index"
        config.DB_PATH = config.DB_DIR / "index.db"
        config.TOOL_REL = None
        self.write("a.py", "def visible_fn():\n    return 1\n")

    def write(self, rel: str, text: str, base: Path | None = None) -> Path:
        p = (base or self.root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def git_init(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True, capture_output=True)


class SafeReadTest(_RepoCase):
    def test_regular_file(self):
        self.assertIsNotNone(safefs.lstat_file("a.py"))
        self.assertEqual(safefs.read_bytes("a.py"), (self.root / "a.py").read_bytes())
        self.assertIsNone(safefs.read_bytes("missing.py"))
        self.assertIsNone(safefs.read_bytes("a.py", max_bytes=3))  # size cap

    def test_rejects_malformed_paths(self):
        self.write("x.py", "x = 1\n", base=self.outside)
        for rel in ("../outside/x.py", "pkg/../a.py", "./a.py", "/a.py", "", "C:/a.py", "a.py\0", "a\\..\\a.py"):
            self.assertIsNone(safefs.read_bytes(rel), rel)
            self.assertIsNone(safefs.lstat_file(rel), rel)

    def test_directory_is_not_a_file(self):
        (self.root / "pkg.py").mkdir()
        self.assertIsNone(safefs.read_bytes("pkg.py"))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs on this platform")
    def test_fifo_is_refused_without_blocking(self):
        os.mkfifo(self.root / "pipe.py")
        self.assertIsNone(safefs.lstat_file("pipe.py"))
        self.assertIsNone(safefs.read_bytes("pipe.py"))  # would hang forever without O_NONBLOCK

    def test_swap_between_check_and_open_is_refused(self):
        # Simulate the Windows fallback losing a race: the path checked is not the file that gets opened.
        self.write("b.py", "y = 2\n")
        other = os.lstat(self.root / "b.py")
        with mock.patch.object(safefs, "_HAVE_AT", False), mock.patch.object(safefs, "lstat_file", return_value=other):
            self.assertIsNone(safefs.read_bytes("a.py"))
        with mock.patch.object(safefs, "_HAVE_AT", False):
            self.assertIsNotNone(safefs.read_bytes("a.py"))  # and the fallback still reads normal files


class LinkTest(_RepoCase):
    """SEC-01 (in-repo alias of an ignored secret) and SEC-02 (linked parent directory)."""

    def test_in_repo_symlink_to_ignored_secret(self):
        self.write(".env", f"SECRET={SECRET}\n")
        self.write(".gitignore", ".env\n")
        _file_link(self.root / "visible.py", self.root / ".env")
        self.assertIsNone(safefs.lstat_file("visible.py"))
        self.assertIsNone(safefs.read_bytes("visible.py"))
        self.git_init()
        indexer.refresh(full=True)
        out = queries.read_symbol_source(file="visible.py", line_start=1, line_end=1)
        self.assertNotIn(SECRET, out)
        self.assertTrue(out.startswith("error"), out)

    def test_symlink_leaving_repo(self):
        secret = self.write("credentials.py", f"KEY = '{SECRET}'\n", base=self.outside)
        _file_link(self.root / "link.py", secret)
        self.assertIsNone(safefs.read_bytes("link.py"))

    def test_linked_parent_directory(self):
        self.write("leaked.py", f'def outside_secret_fn():\n    """{SECRET}"""\n', base=self.outside)
        _dir_link(self.root / "pkg", self.outside)
        self.assertTrue((self.root / "pkg" / "leaked.py").is_file())  # the link really works
        self.assertIsNone(safefs.lstat_file("pkg/leaked.py"))
        self.assertIsNone(safefs.read_bytes("pkg/leaked.py"))
        for walk in (True, False):  # git listing, then the os.walk fallback
            with self.subTest(git=walk):
                if walk:
                    self.git_init()  # Git for Windows lists files inside a junction; git on POSIX does not
                with mock.patch.object(indexer, "_git_files", return_value=None) if not walk else mock.MagicMock():
                    indexer.refresh(full=True)
                self.assertIn("0 matches", queries.search_symbol("outside_secret_fn"))
                self.assertNotIn(SECRET, queries.get_file_summary("pkg/leaked.py"))
                self.assertIn("visible_fn", queries.search_symbol("visible_fn"))  # normal files still indexed


class GitHeadTest(_RepoCase):
    """A copied repo's .git/HEAD must not turn index_stats into a file reader."""

    def head(self, text: str) -> str:
        self.write(".git/HEAD", text + "\n")
        return indexer._git_head()

    def test_ref_traversal_is_not_followed(self):
        self.write("outside_secret.txt", SECRET + "\n", base=self.outside)
        for ref in ("../../outside/outside_secret.txt", "refs/../../../outside/outside_secret.txt",
                    str(self.outside / "outside_secret.txt"), "refs/heads/C:\\x"):
            with self.subTest(ref=ref):
                self.assertNotIn(SECRET, self.head("ref: " + ref))
        # An index written by an older, vulnerable version may already hold the leaked value: it is replaced.
        con = indexer.db()
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('git_head', ?)", (SECRET,))
        con.commit()
        indexer.refresh()
        self.assertNotIn(SECRET, queries.index_stats())
        # Even a hex-looking file outside the repo is not followed (the ref check, not just the sha check).
        sha = "fedcba9876543210fedcba9876543210fedcba98"
        self.write("outside_sha", sha + "\n", base=self.outside)
        for ref in ("../../outside/outside_sha", (self.outside / "outside_sha").as_posix()):
            self.assertEqual(self.head("ref: " + ref), "", ref)

    def test_only_commit_ids_are_returned(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        self.write(".git/refs/heads/main", sha + "\n")
        self.assertEqual(self.head("ref: refs/heads/main"), f"refs/heads/main {sha}")
        self.write(".git/refs/heads/main", SECRET + "\n")
        self.assertEqual(self.head("ref: refs/heads/main"), "refs/heads/main")
        self.assertEqual(self.head(sha), sha)  # detached HEAD
        self.assertEqual(self.head(SECRET), "")


if __name__ == "__main__":
    unittest.main()
