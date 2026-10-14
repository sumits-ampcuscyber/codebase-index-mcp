# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com), versions follow [SemVer](https://semver.org).

## [Unreleased]

### Security
- git fsmonitor command execution blocked (`core.fsmonitor=false`, `safe.bareRepository=explicit`), so a repo's own `.git/config` cannot run commands.
- File reads restricted to indexed files: `read_symbol_source` line ranges and `summarize_file` no longer reach untracked or ignored files such as `.env`.
- Symlinks and Windows junctions are refused in every path component, including links that stay inside the repo (an in-repo `visible.py -> .env` link could expose an ignored secret, and git on Windows lists files inside a junction to another folder). Only regular files are read; a symlinked index folder or database is refused.
- All repo-file reads go through `safefs`: on Linux/macOS a race-free `openat`/`O_NOFOLLOW` walk with checks on the descriptor that is read; on Windows a check/open/compare-file-id sequence.
- `.git/HEAD` handling no longer follows arbitrary `ref:` paths (a crafted HEAD in a copied repo made `index_stats` print any file); only `refs/...` names are followed and only commit ids are shown. A stale value in an existing index is overwritten.
- Git hook script lines are shell-quoted.
- `codebase-index setup` refuses to write through symlinked targets that resolve outside the workspace.
- Limits and depths are clamped.
- CI: least-privilege `GITHUB_TOKEN` permissions, `persist-credentials: false`, pinned actions (commit SHAs), and Dependabot updates for actions and pip.

- Windows: git is run by absolute path from absolute `PATH` entries outside the repo. A bare `git` (and `shutil.which`) also searches the current folder, so a repo started as the server's working folder could ship its own `git.exe` and have it run on every refresh.
- `CODEBASE_OFFLINE=1` disables `summarize_file` even when an API key is present; likely credentials are masked line by line before any file content is sent.
- Server instructions and the installed rule state that tool results are data, not instructions.
- Git hooks coalesce: during a rebase or scripted commits one background worker re-runs as needed instead of one process per commit.
- `setup` warns that generated MCP configs contain absolute local paths; this repo ignores `/.vscode/` and `/.agents/`. The SQLite connection is closed at exit. CI upgrades pip before `pip-audit` (CVE-2026-13346).

### Added
- `codebase-index setup antigravity`: writes `.agents/mcp_config.json` and the `AGENTS.md` instruction block. `setup all` includes it.
- `codebase-index doctor` checks `.agents/mcp_config.json`.
- Platform guide for Google Antigravity.

### Changed
- `setup cursor` writes `"type": "stdio"` in its `.cursor/mcp.json` entry.
- `setup codex` notes the project-scoped option (`.codex/config.toml`, trusted projects only).
- Platform guides refreshed against current vendor docs: Antigravity's global config path is now `~/.gemini/config/mcp_config.json` (was `~/.gemini/antigravity/`); Claude Code approval and `claude mcp reset-project-choices`; Codex timeouts; Cursor MCP Logs; VS Code Restricted Mode and autostart.

## [0.2.0] - 2026-10-04

### Added
- Installable package (`pyproject.toml`, `src/` layout) with two commands: `codebase-index` and `codebase-index-mcp`.
- `codebase-index setup cursor|claude-code|vscode|codex|all`: one command per client; merges existing config,
  idempotent, `--dry-run`. Adds a read-only `codebase-explorer` subagent for Claude Code (Haiku by default).
- `codebase-index config` (generic `mcpServers` JSON), `doctor` (diagnostics), `bench` (tokens saved on your repo).
- `~/.codebase-index.env` and `CODEBASE_INDEX_ENV` as places for API keys when installed with pipx/pip.
- Documentation set: per-platform guides, how it works, tools reference, token savings, configuration,
  troubleshooting, extending. Contributing, security policy, issue templates.

### Changed
- Flat scripts became the `codebase_index` package. `setup_cursor.py`, `print_mcp_config.py`,
  `install_git_hooks.py`, `refresh_detached.py`, `mcp_server.py` are replaced by `codebase-index` subcommands
  and `python -m codebase_index.server`. Re-run `codebase-index setup <client>` to update existing configs.
- Shorter shared instruction block (~200 tokens) to avoid repeating the server instructions.

## [0.1.0]

- Tree-sitter + SQLite index for Python / JS / TS / TSX; 12 MCP tools; compact output; folded skeletons;
  background watcher; Cursor setup and subagent; optional `summarize_file`.
