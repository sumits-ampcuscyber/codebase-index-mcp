# Other MCP clients (Antigravity, Windsurf, Claude Desktop, Zed, Cline, …)

Any client that can launch a local stdio MCP server works. Print a ready-to-paste block with correct
absolute paths:

```bash
cd /path/to/your-repo
codebase-index config            # add --name codebase-index-myrepo to choose the server name
```

Output:

```json
{
  "mcpServers": {
    "codebase-index-myrepo": {
      "command": "/path/to/python",
      "args": ["-m", "codebase_index.server"],
      "env": { "CODEBASE_ROOT": "/path/to/myrepo" }
    }
  }
}
```

Merge it into the client's MCP config (inside the existing `"mcpServers"` object if there is one):

| Client | Config file |
|---|---|
| Google Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Claude Desktop | `claude_desktop_config.json` (Settings → Developer → Edit Config) |
| Cline, Roo Code, Continue, Zed, … | the client's MCP settings screen; the JSON shape is the same or very close (some use `context_servers` or YAML) |

Client config locations change between versions: if a path is wrong, check the client's own MCP docs. The
only parts that matter are **command**, **args** and **env**.

## Teach the agent to use it

The server sends routing instructions when it connects, which many clients show to the model. For clients
that do not, or for stronger steering, add the short rule to the client's instruction file
(`GEMINI.md`, `.windsurfrules`, `.clinerules`, `AGENTS.md`, …). The text is in
[`src/codebase_index/templates/instructions.md`](../../../src/codebase_index/templates/instructions.md) and is
about 200 tokens.

## Requirements for a client

- Launches a stdio server with a command, args and env vars.
- Supports MCP tools (no other MCP feature is used).

If your client is not covered, please [open an issue](https://github.com/sumits-ampcuscyber/codebase-index-mcp/issues)
with its config format and we will add `setup <client>`.
