"""Central configuration. Everything can be overridden with environment variables
or with a ".env" file placed next to this file."""
from __future__ import annotations

import os
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env_file = TOOL_DIR / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
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
    # 1) the repo this tool folder lives in, 2) the repo of the current dir, 3) parent of tool dir
    return _git_root(TOOL_DIR) or _git_root(Path.cwd().resolve()) or TOOL_DIR.parent


REPO_ROOT: Path = _find_root()
DB_DIR: Path = REPO_ROOT / ".codebase-index"
DB_PATH: Path = DB_DIR / "index.db"

try:
    TOOL_REL = TOOL_DIR.relative_to(REPO_ROOT).as_posix()  # e.g. "codebase-index-mcp"
except ValueError:
    TOOL_REL = None  # tool folder is outside the repo

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}

# Generated reports under common names stay out because git ls-files respects .gitignore.
EXCLUDE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".nuxt",
    ".cache", "site-packages", ".codebase-index", ".idea", ".vscode", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
} | {d.strip() for d in os.environ.get("CODEBASE_EXCLUDE_DIRS", "").split(",") if d.strip()}

MAX_FILE_BYTES = int(os.environ.get("CODEBASE_MAX_FILE_BYTES", "1000000"))
