# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com), versions follow [SemVer](https://semver.org).

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
