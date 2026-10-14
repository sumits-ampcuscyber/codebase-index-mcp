# Google Antigravity

Antigravity reads MCP servers from a JSON file with a top-level `mcpServers` object. `codebase-index` writes
that file for the current repo, plus the same instruction block that Codex uses in `AGENTS.md`.

## Set up

From your repo root:

```bash
codebase-index setup antigravity
```

It writes into `<repo>/`, merging with what is already there:

| File | Purpose |
|---|---|
| `.agents/mcp_config.json` | The MCP server entry (absolute Python path + `CODEBASE_ROOT`) |
| `AGENTS.md` | A short instruction block between `<!-- codebase-index:start/end -->` markers: use the index before reading files |

Antigravity has no subagent from this tool; the server and the instruction block are all it needs.

Then reload the configuration so Antigravity picks up the server:

- **Antigravity CLI:** type `/mcp`, open the MCP Manager and reload the configurations.
- **Antigravity app:** click the refresh button under **Installed MCP Servers**.

The server should be listed with 12 tools.

Options: `--name <server-name>`, `--workspace <folder>`, `--dry-run`.

### Global alternative (every project)

To register the server in your user config instead of one repo, run `codebase-index config` inside the repo
and merge the printed `mcpServers` entry into `~/.gemini/config/mcp_config.json` (inside the existing
`"mcpServers"` object if there is one). Each repo still needs its own `CODEBASE_ROOT`, so use `--name` to keep
several entries apart. Then reload as above.

## Rules

Antigravity reads `AGENTS.md` at the project root, so `setup` is enough. For more control, add a rule file
under `.agents/rules/` with YAML frontmatter. Copy the block from `AGENTS.md` into it:

```markdown
---
trigger: always_on
---

Use the codebase-index tools before reading whole files.
```

`trigger` can also be `model_decision`, `glob` or `manual`. Global rules live in `~/.gemini/config/rules/*.md`.

## Use it

Just ask normally. The instruction block steers the agent:

- *"Where is `UserService` defined and what are its public methods?"* → `search_symbol`, `get_file_summary`
- *"Show me `save`"* → `read_symbol_source` (huge functions arrive as a folded skeleton)
- *"What breaks if I change `check_token`?"* → `find_callers depth=2`

## Tips for fewer tokens

- Keep the `AGENTS.md` block. Without it the agent tends to open whole files.
- Save files before asking; unsaved buffers are not indexed.
- Use `read_symbol_source` with `line_start` / `line_end` to read part of a large function.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server not listed | Check `.agents/mcp_config.json` exists and has a top-level `mcpServers` object (or the global file at `~/.gemini/config/mcp_config.json`), then reload |
| Tools missing after setup | Reload in the CLI (`/mcp`) or click refresh under **Installed MCP Servers**; restart if that does not help |
| Server fails on start | Run `codebase-index doctor` (it checks this file); the usual cause is a moved or deleted venv: re-run `setup antigravity` |
| Wrong repo in answers | `index_stats` shows the root; fix `CODEBASE_ROOT` in the entry's `env` |
| Agent opens whole files | Check the `AGENTS.md` block is there, and ask "use the codebase index" |
| Old path `~/.gemini/antigravity/mcp_config.json` | Outdated. Use `~/.gemini/config/mcp_config.json` for global config |

More: [troubleshooting](../troubleshooting.md).
