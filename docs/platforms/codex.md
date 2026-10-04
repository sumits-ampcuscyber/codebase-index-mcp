# OpenAI Codex (CLI / IDE extension)

Codex stores MCP servers in your **global** `~/.codex/config.toml`, so `codebase-index` does not edit that
file for you. It writes the repo-local instructions and prints the exact command to register the server.

## Set up

From your repo root:

```bash
codebase-index setup codex
```

1. It adds a short block to `AGENTS.md` (between `<!-- codebase-index:start/end -->` markers) that tells the
   agent to use the index before reading files. Codex reads `AGENTS.md` automatically.
2. It prints a registration command. Run it:

   ```bash
   codex mcp add codebase-index-myrepo --env CODEBASE_ROOT=/path/to/myrepo -- /path/to/python -m codebase_index.server
   ```

   or paste the TOML it prints into `~/.codex/config.toml`:

   ```toml
   [mcp_servers.codebase-index-myrepo]
   command = "/path/to/python"
   args = ["-m", "codebase_index.server"]
   env = { CODEBASE_ROOT = "/path/to/myrepo" }
   ```

3. Restart Codex. Use `/mcp` in the Codex TUI to confirm the server and its tools are listed.

The server is registered globally, so register one entry per repo (the name includes the repo name) and
run Codex in the matching repo.

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
| Server not listed | Check `~/.codex/config.toml` has the `[mcp_servers.<name>]` table; restart Codex |
| Server fails on start | `codebase-index doctor`; make sure `command` is the Python that has the package installed |
| Wrong repo | Fix `CODEBASE_ROOT` in the server's `env` |

More: [troubleshooting](../troubleshooting.md).
