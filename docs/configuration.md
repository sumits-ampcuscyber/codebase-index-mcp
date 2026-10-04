# Configuration

Everything has a working default. Set variables in the MCP config's `env` block, in your shell, or in a
`.env` file. **Real environment variables win over `.env` files.**

## Where `.env` is read from

First file that sets a variable wins:

1. the file named by `CODEBASE_INDEX_ENV`
2. `.env` in the project folder (only when running from a git clone or editable install)
3. `~/.codebase-index.env` (best place for API keys when installed with pipx/pip)

Copy [`.env.example`](../.env.example) as a starting point. Lines look like `KEY=value`; `#` starts a comment;
empty values are ignored.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `CODEBASE_ROOT` | git root of the current directory | Absolute path of the repo to index. `setup` writes it into the MCP config |
| `CODEBASE_WATCH_INTERVAL` | `2` | Seconds between background re-scans while the server runs; `0` = off |
| `CODEBASE_MAX_FILE_BYTES` | `1000000` | Skip files larger than this |
| `CODEBASE_EXCLUDE_DIRS` | none | Extra folder names to skip (comma-separated) |
| `CODEBASE_INDEX_WORKERS` | CPUs − 1 (max 8) | Parser processes for big (2,000+ file) index runs; `1` = in-process |
| `CODEBASE_INDEX_ENV` | none | Path of an extra `.env` file to load |
| `CURSOR_SUBAGENT_MODEL` | `grok-4.7` | Model written into the Cursor subagent by `setup cursor` |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | none | Enables `summarize_file` with Gemini (default `gemini-2.5-flash`) |
| `ANTHROPIC_API_KEY` | none | Enables `summarize_file` with Claude (default `claude-haiku-4-5`; needs `pip install anthropic`) |
| `CHEAP_MODEL_PROVIDER`, `CHEAP_MODEL` | auto | Choose provider (`gemini`/`anthropic`) and model for `summarize_file` |

`summarize_file` answers are cached by (file content, line range, question, model). Without a key every other
tool works and `summarize_file` replies with a clear "no key" message.

## What is indexed

- Source files with extensions `.py`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.mts`, `.cts`, `.tsx`.
- Files come from `git ls-files`, so **`.gitignore` is respected**. Without git, the folder is walked.
- Always skipped: `node_modules`, `.venv`, `venv`, `dist`, `build`, `.next`, `.nuxt`, `__pycache__`, `.git`,
  `coverage`, `.cache`, `site-packages`, `.tox`, `.turbo`, tool caches, and the index folder itself.
- The index lives in `<repo>/.codebase-index/index.db` and git-ignores itself.

## Multiple repos and layouts

| Layout | Setup |
|---|---|
| One repo | `cd repo && codebase-index setup <client>` |
| Several repos | Run `setup` in each: each gets a unique server name and its own `.codebase-index/` |
| Tool cloned inside the repo (`repo/codebase-index-mcp/`) | Works; the enclosing git root is found and the tool folder is never indexed |
| Monorepo with several tsconfigs | Supported: each tsconfig's `paths` apply to files under its folder (deepest first) |
| Index a repo from elsewhere | `CODEBASE_ROOT=/abs/path codebase-index index` |

## Freshness

| Trigger | What happens |
|---|---|
| Server starts | Background watcher syncs immediately, then every `CODEBASE_WATCH_INTERVAL` seconds |
| Any tool call | Syncs first if the watcher has not synced in the last interval + 1 s |
| `git commit/checkout/merge/rebase` | Optional hooks (`codebase-index hooks`) start a detached refresh |
| `reindex` tool / `codebase-index index` | Explicit sync (`--full` rebuilds) |
