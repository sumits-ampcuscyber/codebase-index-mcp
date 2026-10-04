# Claude Code

## Set up

From your repo root:

```bash
codebase-index setup claude-code
```

It writes (merging with what is there):

| File | Purpose |
|---|---|
| `.mcp.json` | Project-scoped MCP server entry (shared with your team if you commit it; contains a machine-specific Python path, so many teams keep it out of git and have each person run `setup`) |
| `CLAUDE.md` | A short instruction block between `<!-- codebase-index:start/end -->` markers: use the index before reading files |
| `.claude/agents/codebase-explorer.md` | Read-only subagent for multi-file questions, **pinned to Haiku** |

Start `claude` in the repo and approve the project server when prompted. Check with `/mcp`: the
`codebase-index-<repo>` server should be connected with 12 tools.

Prefer the CLI over a file? `setup` prints the equivalent command:

```bash
claude mcp add codebase-index-myrepo --scope project -e CODEBASE_ROOT=/path/to/myrepo -- /path/to/python -m codebase_index.server
```

Drop `--scope project` for a personal (local) server that is not shared.

Options: `--model haiku|sonnet|opus|inherit` (subagent model), `--no-subagent`, `--name`, `--workspace`, `--dry-run`.

## Use it

Ask as usual. Claude Code sees the tools as `mcp__codebase-index-<repo>__search_symbol` and so on.

- Locating / outlining / reading one function → the index tools directly.
- *"How does X work across the codebase?"* → Claude delegates to the `codebase-explorer` subagent, which does
  the reading on Haiku in its own context window and returns a short answer. Your main conversation (and its
  more expensive model) never holds the raw source.
- To force it: *"use the codebase-explorer agent to trace how a request reaches the database"*.

## Keeping the cost down

- **Check what you pay for:** `/context` shows how much of the window the MCP tools take. The 12 tool
  definitions are roughly 1,500 tokens once per session; one avoided large-file read pays that back.
- **Do not duplicate instructions.** The server already sends routing instructions at connect. The
  `CLAUDE.md` block is deliberately short (~200 tokens); do not paste the tool docs there as well.
- **Subagent model.** Haiku is cheap and good at "find and summarize". Use `--model sonnet` if its answers are
  too shallow for your codebase.
- **Permissions.** To stop approval prompts for the read-only tools, allow the server in `.claude/settings.json`:
  `{"permissions": {"allow": ["mcp__codebase-index-myrepo"]}}` (use your server name).
- **Long sessions.** Everything stays in context and is re-sent each turn, which is why folded skeletons and
  ranges matter more than they look: prefer `read_symbol_source` with `line_start`/`line_end` over reading files.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/mcp` shows failed or tools missing | `codebase-index doctor`; make sure the Python path in `.mcp.json` still exists, then re-run `setup claude-code` |
| Server not prompting for approval | Project servers need one-time approval; run `claude mcp list` and re-approve |
| Connection timeout on start | First start builds the index. Run `codebase-index index` once beforehand on very large repos |

More: [troubleshooting](../troubleshooting.md).
