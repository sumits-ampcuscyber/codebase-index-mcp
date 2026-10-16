# OpenAI Codex (CLI / IDE extension)

Codex reads MCP servers from `[mcp_servers.<name>]` tables in your **global** `~/.codex/config.toml`, or from
`.codex/config.toml` in a project (Codex only loads project config for trusted projects). `codebase-index`
writes the repo-local instructions and can either write the project config or print the exact command/TOML to
register the server.

## Set up

From your repo root:

```bash
codebase-index setup codex
```

1. It adds a short block to `AGENTS.md` (between `<!-- codebase-index:start/end -->` markers) that tells the
   agent to use the index before reading files. Codex reads `AGENTS.md` automatically.
2. Choose how to register the server.

   For a project-local, one-command setup (the project must be trusted):

   ```bash
   codebase-index setup codex --codex-scope project
   ```

   This writes `.codex/config.toml` and preserves unrelated TOML content. Or let the default setup print a
   registration command and run it globally, available in every project:

   ```bash
   codex mcp add codebase-index-myrepo --env CODEBASE_ROOT=/path/to/myrepo -- /path/to/python -m codebase_index.server
   ```

   You can also paste the TOML it prints into `~/.codex/config.toml` (global):

   ```toml
   [mcp_servers.codebase-index-myrepo]
   command = "/path/to/python"
   args = ["-m", "codebase_index.server"]
   env = { CODEBASE_ROOT = "/path/to/myrepo" }
   ```

   The project-scoped version is generated for you by `setup codex --codex-scope project`.

3. Restart Codex. Use `/mcp` in the Codex TUI to confirm the server and its tools are listed.

Each entry is per repo, so the name includes the repo name. With the global file, run Codex in the matching repo.

Optional keys: `cwd`, `enabled`, `startup_timeout_sec` (default 10) and `tool_timeout_sec` (default 60). Raise
`startup_timeout_sec` if the first start on a very large repo times out. `codebase-index doctor` checks both
the project config and the usual user config when it can find a codebase-index entry.

## Use it

Ask normally. With the `AGENTS.md` block in place, Codex should prefer `search_symbol`, `get_file_summary`
and `read_symbol_source` over shell `cat` / `rg` on source files.

## Tips for fewer tokens

- Codex tends to explore with shell commands. The `AGENTS.md` block is what redirects it; keep it.
- `read_symbol_source` with `line_start` / `line_end` is the cheapest way to read part of a large function.
- Run `codebase-index bench` to see what your largest files would cost to read in full.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server not listed | The top-level key must be `mcp_servers` (underscore) and the table `[mcp_servers.<name>]`; check `~/.codex/config.toml`, then restart Codex |
| Project config ignored | Codex loads `.codex/config.toml` only for trusted projects; trust the project or use the global file |
| Server fails on start | `codebase-index doctor`; make sure `command` is the Python that has the package installed |
| Start times out on a big repo | Raise `startup_timeout_sec` (default 10) |
| Tool calls time out | Raise `tool_timeout_sec` (default 60) for that server |
| Wrong repo | Fix `CODEBASE_ROOT` in the server's `env` |

More: [troubleshooting](../troubleshooting.md).
