# Command line reference

`codebase-index <command>`. The repo is the git root of the current directory, or `$CODEBASE_ROOT`.
Run any command with `--help` for its options.

## Set up and maintain

| Command | Purpose |
|---|---|
| `setup <client>` | Configure a client for this repo. `client`: `cursor`, `claude-code`, `vscode`, `codex`, `all` |
| `config` | Print generic `mcpServers` JSON for any other client |
| `doctor` | Diagnose install, repo, index and client wiring |
| `bench [--top N]` | Tokens saved vs reading the N largest files (default 8) |
| `hooks [--uninstall]` | Git hooks that refresh the index after commit / checkout / merge / rebase |
| `index [--full] [--quiet]` | Build or refresh the index (`--full` rebuilds from scratch) |
| `stats` | Index health: root, counts, last sync, git HEAD |

### `setup` options

| Option | Meaning |
|---|---|
| `--workspace <dir>` | Folder to write config into and index (default: the current repo) |
| `--name <name>` | MCP server name (default `codebase-index-<repo>`) |
| `--model <id>` | Subagent model. Cursor: a model id (default `grok-4.7`). Claude Code: `haiku` (default), `sonnet`, `opus`, `inherit` |
| `--no-subagent` | Do not install the `codebase-explorer` subagent |
| `--dry-run` | Show what would be written, change nothing |

## Query (same answers the assistant gets)

| Command | Tool | Example |
|---|---|---|
| `map [path] [--limit N]` | `repo_map` | `codebase-index map src/api` |
| `search "<query>" [--kind K]` | `search_symbol` | `codebase-index search "UserService, accept evidence"` |
| `summary <file> [--depth 2]` | `get_file_summary` | `codebase-index summary app/models.py` |
| `exports <file>` | `get_exports` | |
| `source <symbols> [--file F] [--mode auto\|full\|skeleton]` | `read_symbol_source` | `codebase-index source UserService.save` |
| `callers <symbol> [--receiver R] [--depth N]` | `find_callers` | `codebase-index callers save --depth 2` |
| `callees <symbol>` | `find_callees` | |
| `importers <file>` | `who_imports` | |
| `routes [query] [--method M]` | `find_route` | `codebase-index routes /users --method GET` |
| `ask <file> "<question>"` | `summarize_file` | needs an API key |

Output format and argument details: [tools reference](tools.md).

## Other entry points

| Command | Purpose |
|---|---|
| `codebase-index-mcp` | Start the MCP server on stdio (what editors launch) |
| `python -m codebase_index.server` | Same, using an explicit Python. This is what `setup` writes into configs |
| `python -m codebase_index ...` | Same as `codebase-index ...` |
