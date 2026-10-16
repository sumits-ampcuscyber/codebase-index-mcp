# VS Code (GitHub Copilot)

Requires a VS Code version with MCP support and Copilot Chat in **Agent mode**.

## Set up

From your repo root:

```bash
codebase-index setup vscode
```

| File | Purpose |
|---|---|
| `.mcp.json` | Portable workspace MCP server entry with a top-level `mcpServers` key. This is also understood by Claude Code and Copilot harness sessions |
| `.github/copilot-instructions.md` | A short instruction block between `<!-- codebase-index:start/end -->` markers |

Then open the folder as a **trusted** workspace. In Restricted Mode, VS Code blocks workspace MCP config, so the
server will not appear until you trust the folder. In a trusted workspace the server can start without a separate
trust prompt.

Start it with **MCP: List Servers** or reload the window. Servers can also start when you send a chat message
(`chat.mcp.autostart`). Open Copilot Chat, switch to **Agent** mode, and check the tools picker: the 12
codebase-index tools should be listed.

Options: `--name`, `--workspace`, `--dry-run`. (VS Code has no per-server subagent model, so there is no subagent.)

The older VS Code-specific format is still supported by VS Code: `.vscode/mcp.json` with a top-level `servers`
object. Use it when you need VS Code-only features such as input variables or per-server sandboxing; copy the
entry from `.mcp.json` and change the wrapper key.

## Use it

Ask in Agent mode: *"Find where `accept_evidence` is defined and show its callers."* The agent should call
`search_symbol` and `find_callers` instead of opening files. You can also reference a tool explicitly in chat
with `#` (for example `#search_symbol`) to nudge the agent.

## Tips

- Commit `.mcp.json` only if your team shares the same Python path; otherwise add it to `.gitignore` and let
  each developer run `setup vscode`. The generated file uses an absolute Python path and `CODEBASE_ROOT`.
  For a team-shared config, replace the command with a common `codebase-index-mcp` executable and use the
  workspace's portable configuration format.
- Save files before asking: unsaved editor buffers are not indexed.
- Tool results count against context just like file reads: prefer `get_file_summary` and
  `read_symbol_source` ranges over opening files in the chat.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server missing in "MCP: List Servers" | Check `.mcp.json` has a `mcpServers` object, trust the workspace, then run `codebase-index doctor` |
| Nothing starts, workspace is in Restricted Mode | Trust the folder (Manage Workspace Trust), then reload the window |
| Server fails to start | Open the server's output (List Servers → Show Output). Usually the Python path is stale: re-run `setup vscode` |
| Server starts when you send a chat message, not before | That is `chat.mcp.autostart`. Start it manually from List Servers, or change the setting |
| Tools not offered in chat | Use **Agent** mode, and enable the server's tools in the tools picker |

More: [troubleshooting](../troubleshooting.md).
