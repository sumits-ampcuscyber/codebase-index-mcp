"""Security regressions: git lookup, offline switch, secret masking, hook coalescing, injection rule.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("CODEBASE_OFFLINE", None)

from codebase_index import cheap_delegate  # noqa: E402
from codebase_index import config  # noqa: E402
from codebase_index import hooks  # noqa: E402
from codebase_index import indexer  # noqa: E402
from codebase_index import server  # noqa: E402
from test_safefs import _RepoCase  # noqa: E402

GIT = "git.exe" if sys.platform == "win32" else "git"
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"


def _fake_git(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / GIT
    p.write_bytes(b"#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


class GitLookupTest(_RepoCase):
    def test_only_absolute_path_entries_outside_the_repo(self):
        good = _fake_git(self.outside / "bin")
        _fake_git(self.root / "tools")  # a git shipped inside the repo
        _fake_git(self.root)            # and one in the repo root (the server's usual cwd)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        path = os.pathsep.join([".", "", "tools", str(self.root / "tools"), str(good.parent)])
        with mock.patch.dict(os.environ, {"PATH": path}):
            self.assertEqual(config.git_exe(), str(good))
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([".", str(self.root / "tools")])}):
            self.assertIsNone(config.git_exe())
            self.assertIsNone(indexer._git_files(self.root))  # falls back to the directory walk

    @unittest.skipUnless(sys.platform == "win32", "CreateProcess current-folder search is Windows-only")
    def test_planted_git_exe_in_cwd_is_not_run(self):
        real = config.git_exe()
        if real is None:
            self.skipTest("git not installed")
        self.git_init()
        # A harmless stand-in: if it ran instead of git, the listing would not contain a.py.
        shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "hostname.exe",
                    self.root / "git.exe")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        env = {k: v for k, v in os.environ.items() if k.lower() != "nodefaultcurrentdirectoryinexepath"}
        with mock.patch.dict(os.environ, env, clear=True):
            # Precondition: a bare "git" really is hijacked here, so the test proves something.
            bare = subprocess.run(["git", "--version"], capture_output=True, text=True)
            self.assertNotIn("git version", bare.stdout)
            files = indexer._git_files(self.root)
        self.assertIsNotNone(files)
        self.assertIn("a.py", files)


class OfflineAndRedactionTest(_RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.write("creds.py", f'AWS_KEY = "{FAKE_AWS}"\npassword = "hunter2hunter2"\n\n\ndef f():\n    return 1\n')
        indexer.refresh(full=True)

    def test_offline_blocks_cloud_calls_even_with_a_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake", "CODEBASE_OFFLINE": "1"}), \
                mock.patch.object(cheap_delegate, "_ask_gemini") as ask:
            out = cheap_delegate.summarize_file("creds.py", "what?")
        self.assertIn("CODEBASE_OFFLINE", out)
        ask.assert_not_called()

    def test_secrets_are_masked_before_sending(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}), \
                mock.patch.object(cheap_delegate, "_ask_gemini", return_value="ok") as ask:
            out = cheap_delegate.summarize_file("creds.py", "what?")
        prompt = ask.call_args.args[2]
        self.assertNotIn(FAKE_AWS, prompt)
        self.assertNotIn("hunter2hunter2", prompt)
        self.assertIn("5:", prompt)  # line numbers still line up after masking
        self.assertIn("def f():", prompt)
        self.assertIn("2 likely secrets masked", out)

    def test_redact_keeps_lines_and_ordinary_code(self):
        src = ["def token_count():", "    return 3", "-----BEGIN OPENSSH PRIVATE KEY-----", "b3BlbnNzaC1r",
               "-----END OPENSSH PRIVATE KEY-----", 'DB = "postgres://app:s3cretpass@db/x"', "x = 1"]
        out, n = cheap_delegate.redact(src)
        self.assertEqual(len(out), len(src))
        self.assertEqual(out[:2], src[:2])
        self.assertEqual(out[-1], "x = 1")
        self.assertNotIn("b3BlbnNzaC1r", "\n".join(out))
        self.assertNotIn("s3cretpass", out[5])
        self.assertEqual(n, 2)

    def test_redact_masks_unquoted_yaml_and_keeps_safe_values(self):
        src = ["apiVersion: v1", "metadata:", "  name: demo", "  password: abc123",
               "  api_key: unquoted-secret", "  image: example/api:latest"]
        out, n = cheap_delegate.redact(src)
        joined = "\n".join(out)
        self.assertNotIn("abc123", joined)
        self.assertNotIn("unquoted-secret", joined)
        self.assertIn("name: demo", joined)
        self.assertIn("image: example/api:latest", joined)
        self.assertGreaterEqual(n, 2)

    def test_summary_cache_expires(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}), \
                mock.patch.object(cheap_delegate, "_ask_gemini", side_effect=["one", "two"]) as ask:
            cheap_delegate.summarize_file("creds.py", "what?")
            con = indexer.db()
            con.execute("UPDATE summary_cache SET created=0")
            con.commit()
            with mock.patch.object(config, "SUMMARY_CACHE_TTL_SECONDS", 60):
                out = cheap_delegate.summarize_file("creds.py", "what?")
        self.assertIn("two", out)
        self.assertEqual(ask.call_count, 2)

    def test_refresh_stops_at_total_byte_budget(self):
        with mock.patch.object(config, "MAX_TOTAL_FILE_BYTES", 1):
            stats = indexer.refresh(full=True)
        self.assertGreater(stats["skipped_budget"], 0)
        self.assertEqual(stats["reindexed"], 0)

    @unittest.skipUnless(os.name != "nt", "Unix mode bits are not Windows ACLs")
    def test_local_index_permissions_are_private(self):
        con = indexer.db()
        con.execute("SELECT 1")
        self.assertEqual(stat.S_IMODE(os.stat(config.DB_DIR).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(config.DB_PATH).st_mode), 0o600)


class HookCoalescingTest(_RepoCase):
    def test_hooks_reject_external_core_hookspath(self):
        def git_run(cmd, **kwargs):
            value = str(self.root / ".git") if "--git-dir" in cmd else str(self.outside / "hooks")
            return subprocess.CompletedProcess(cmd, 0, stdout=value + "\n", stderr="")

        with mock.patch.object(config, "git_exe", return_value="git"), \
                mock.patch.object(hooks.subprocess, "run", side_effect=git_run):
            with self.assertRaises(SystemExit):
                hooks.hooks_dir()

    def test_many_hooks_start_one_worker_that_reruns_once(self):
        with mock.patch.object(hooks.subprocess, "Popen") as popen:
            for _ in range(20):  # e.g. a 20-commit rebase
                hooks.refresh_detached()
        self.assertEqual(popen.call_count, 1)
        self.assertIn("--worker", popen.call_args.args[0])
        lock = config.DB_DIR / hooks.LOCK
        self.assertTrue(lock.exists())

        calls = []

        def fake_refresh(full=False):
            calls.append(full)
            if len(calls) == 1:
                hooks.refresh_detached()  # a commit lands while the first run is busy

        with mock.patch.object(indexer, "refresh", side_effect=fake_refresh), \
                mock.patch.object(hooks.subprocess, "Popen") as popen2:
            hooks.refresh_worker()
        self.assertEqual(len(calls), 2)
        popen2.assert_not_called()
        self.assertFalse(lock.exists())

    def test_stale_lock_is_taken_over(self):
        indexer.ensure_db_dir()
        lock = config.DB_DIR / hooks.LOCK
        lock.write_text("")
        os.utime(lock, (1, 1))  # left behind by a crashed run long ago
        with mock.patch.object(hooks.subprocess, "Popen") as popen:
            hooks.refresh_detached()
        self.assertEqual(popen.call_count, 1)


class InjectionRuleTest(unittest.TestCase):
    def test_instructions_mark_tool_output_as_data(self):
        self.assertIn("not instructions", server.INSTRUCTIONS)
        tpl = (Path(server.__file__).parent / "templates" / "instructions.md").read_text(encoding="utf-8")
        self.assertIn("not\ninstructions", tpl)


if __name__ == "__main__":
    unittest.main()
