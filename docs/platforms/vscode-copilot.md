# VS Code (GitHub Copilot)

Requires a VS Code version with MCP support and Copilot Chat in **Agent mode**.

## Set up

From your repo root:

```bash
codebase-index setup vscode
```

| File | Purpose |
|---|---|
| `.vscode/mcp.json` | MCP server entry. VS Code's schema uses a top-level `servers` key (not `mcpServers`) |
| `.github/copilot-instructions.md` | A short instruction block between `<!-- codebase-index:start/end -->` markers |

Then: Command Palette → **MCP: List Servers** → select `codebase-index-<repo>` → **Start Server** (or reload the
window). Open Copilot Chat, switch to **Agent** mode, and check the tools picker: the 12 codebase-index tools
should be listed.

Options: `--name`, `--workspace`, `--dry-run`. (VS Code has no per-server subagent model, so there is no subagent.)

## Use it

Ask in Agent mode: *"Find where `accept_evidence` is defined and show its callers."* The agent should call
`search_symbol` and `find_callers` instead of opening files. You can also reference a tool explicitly in chat
with `#` (for example `#search_symbol`) to nudge the agent.

## Tips

- Commit `.vscode/mcp.json` only if your team shares the same Python path; otherwise add it to `.gitignore`
  and let each developer run `setup vscode`. (Alternatively edit it to use `${workspaceFolder}` for
  `CODEBASE_ROOT`, and a `codebase-index-mcp` command that is on everyone's PATH from `pipx`.)
- Save files before asking: unsaved editor buffers are not indexed.
- Tool results count against context just like file reads: prefer `get_file_summary` and
  `read_symbol_source` ranges over opening files in the chat.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server missing in "MCP: List Servers" | The file must be `.vscode/mcp.json` with a `servers` object; run `codebase-index doctor` |
| Server fails to start | Open the server's output (List Servers → Show Output). Usually the Python path is stale: re-run `setup vscode` |
| Tools not offered in chat | Use **Agent** mode, and enable the server's tools in the tools picker |

More: [troubleshooting](../troubleshooting.md).
