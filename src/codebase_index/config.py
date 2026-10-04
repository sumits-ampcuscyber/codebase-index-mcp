"""Central configuration. Everything is overridden with environment variables.

Environment variables can also come from a ".env" file. Searched in this order (the real environment
always wins, and the first file that sets a variable wins):
  1. the file named by CODEBASE_INDEX_ENV
  2. ".env" in the source checkout (only when running from a git clone / editable install)
  3. "~/.codebase-index.env" (a good place for API keys when installed with pipx / pip)
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
# The project folder when running from a clone (src/codebase_index -> project); None when pip-installed.
SOURCE_DIR = PACKAGE_DIR.parents[1] if (PACKAGE_DIR.parents[1] / "pyproject.toml").is_file() else None


def _load_dotenv() -> None:
    candidates = []
    if os.environ.get("CODEBASE_INDEX_ENV"):
        candidates.append(Path(os.environ["CODEBASE_INDEX_ENV"]).expanduser())
    if SOURCE_DIR:
        candidates.append(SOURCE_DIR / ".env")
    candidates.append(Path.home() / ".codebase-index.env")
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.split(" #", 1)[0].strip().strip('"').strip("'")
            if key and value and key not in os.environ:  # empty values are ignored
                os.environ[key] = value


_load_dotenv()


def _git_root(start: Path):
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return None


def _find_root() -> Path:
    env = os.environ.get("CODEBASE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # 1) the repo this tool is vendored into (running from a clone inside it), 2) the repo of the
    # current directory. A git root equal to SOURCE_DIR is this tool's own clone, never the target.
    starts = ([SOURCE_DIR.parent] if SOURCE_DIR else []) + [Path.cwd().resolve()]
    for start in starts:
        root = _git_root(start)
        if root is not None and root != SOURCE_DIR:
            return root
    return Path.cwd().resolve()


REPO_ROOT: Path = _find_root()
DB_DIR: Path = REPO_ROOT / ".codebase-index"
DB_PATH: Path = DB_DIR / "index.db"

try:
    TOOL_REL = SOURCE_DIR.relative_to(REPO_ROOT).as_posix() if SOURCE_DIR else None  # e.g. "codebase-index-mcp"
except ValueError:
    TOOL_REL = None  # tool folder is outside the repo
if TOOL_REL == ".":
    TOOL_REL = None  # the tool IS the repo being indexed (e.g. developing this project)

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
}

# Generated reports under common names stay out because git ls-files respects .gitignore.
EXCLUDE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".nuxt",
    ".cache", "site-packages", ".codebase-index", ".idea", ".vscode", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".turbo",
} | {d.strip() for d in os.environ.get("CODEBASE_EXCLUDE_DIRS", "").split(",") if d.strip()}

MAX_FILE_BYTES = int(os.environ.get("CODEBASE_MAX_FILE_BYTES", "1000000"))

# Seconds between background re-scans while the MCP server runs; 0 turns the watcher off.
WATCH_INTERVAL = float(os.environ.get("CODEBASE_WATCH_INTERVAL", "2"))

# Parser processes for big (re)index runs. 0 or 1 = parse in-process.
WORKERS = int(os.environ.get("CODEBASE_INDEX_WORKERS", str(max(1, min(8, (os.cpu_count() or 2) - 1)))))

# Model that the Cursor "codebase-explorer" subagent runs on (written by `codebase-index setup cursor`).
CURSOR_SUBAGENT_MODEL = os.environ.get("CURSOR_SUBAGENT_MODEL", "grok-4.7")
