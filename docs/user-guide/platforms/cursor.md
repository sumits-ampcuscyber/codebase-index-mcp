# Cursor

## Set up

From your repo (the folder you open in Cursor):

```bash
codebase-index setup cursor
```

It writes into `<repo>/.cursor/`, merging with what is already there:

| File | Purpose |
|---|---|
| `mcp.json` | The MCP server entry (absolute Python path + `CODEBASE_ROOT`) |
| `rules/codebase-index.mdc` | Always-on rule: use the index tools before reading files |
| `agents/codebase-explorer.md` | Read-only subagent for multi-file questions, **pinned to Grok 4.7** |

Then restart Cursor, or toggle the server under **Settings → MCP**. A green dot and 12 tools means it works.

Options: `--model <id>` (subagent model), `--no-subagent`, `--name <server-name>`, `--workspace <folder>`,
`--dry-run`.

## Use it

Just ask normally. The rule steers the agent:

- *"Where is `UserService` defined and what are its public methods?"* → `search_symbol`, `get_file_summary`
- *"Show me `save`"* → `read_symbol_source` (huge functions arrive as a folded skeleton)
- *"What breaks if I change `check_token`?"* → `find_callers depth=2`
- *"How does login work end to end?"* → the **codebase-explorer** subagent does the multi-file reading on a
  cheap model and returns ~300 words with `path:line` references. The raw source never enters your chat.

## Choosing the subagent model

Default: `grok-4.7`. Change it any of these ways:

```bash
codebase-index setup cursor --model <model-id>       # rewrites .cursor/agents/codebase-explorer.md
```

- or set `CURSOR_SUBAGENT_MODEL=<model-id>` in `~/.codebase-index.env`, then re-run `setup cursor`
- or edit the `model:` line in `.cursor/agents/codebase-explorer.md` by hand

Use the id exactly as Cursor's model picker shows it. `inherit` (same as the chat) and `fast` also work.

## Tips for fewer tokens

- Keep the always-on rule: it is the thing that makes the agent reach for the index first.
- Save files before asking; unsaved buffers are not indexed.
- For a big refactor, ask for `find_callers depth=2` first and read only the call sites it lists.
- Using several repos? Run `setup` in each one; each gets its own server name and its own index.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server red / no tools | Run `codebase-index doctor`; the usual cause is a moved or deleted venv: re-run `setup cursor` |
| Subagent model not found | Use the exact id from Cursor's model picker: `setup cursor --model <id>` |
| Wrong repo in answers | `index_stats` shows the root; fix `CODEBASE_ROOT` in `.cursor/mcp.json` |

More: [troubleshooting](../troubleshooting.md).
