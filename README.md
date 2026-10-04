# codebase-index-mcp

**Make your AI coding assistant cheaper and faster by giving it a map of your code.**

AI assistants (Cursor, Claude Code, Codex, GitHub Copilot) normally find things by opening whole files,
which burns thousands of tokens each time and keeps burning them on every later message. This tool builds a
small local index of your project, so the assistant can ask *"where is `UserService`?"* or *"who calls
`save`?"* and get a precise answer in a few hundred tokens.

- **Free and private.** It uses a code parser, not an AI model. Nothing leaves your machine.
- **Works with your editor.** Cursor, Claude Code, VS Code (Copilot), Codex, and any MCP client.
- **Set up in one command**, per project. Stays up to date on its own.
- Supports **Python, JavaScript / JSX, TypeScript / TSX**.

## What it saves

Measured on a real 749-file Python + React/TypeScript repo (204k lines):

| Question | Open the file(s) | With the index |
|---|---|---|
| Outline of a 5,195-line component | ~64,000 tokens | ~2,700 |
| Code of a 4,028-line component | ~50,000 tokens | ~2,300, then only the part you need |
| Where is anything named `get`? | grep + opening files | ~710 |
| Get oriented in an unfamiliar repo | several turns of browsing | ~900 |

Run `codebase-index bench` after installing to see the numbers for **your** project.
Details, and the honest overhead: [Token savings](docs/concepts/token-savings.md).

---

## Get started in 3 steps

You need **Python 3.10+** and **git**. New to this? Follow the beginner version:
**[Quick start](docs/user-guide/quick-start.md)**.

**1. Install once per computer**

```bash
pipx install git+https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
```

**2. Switch it on in your project** (run inside the project folder)

```bash
cd path/to/your-project
codebase-index setup cursor        # or: claude-code | vscode | codex | all
```

**3. Restart your editor and ask:**

> *"Use the codebase index to find where `<something>` is defined and show me its code."*

That is the whole thing. Check the wiring any time with `codebase-index doctor`.

### Guide for your editor

| Editor / agent | What `setup` configures | Guide |
|---|---|---|
| **Cursor** | MCP server, an always-on rule, a cheap read-only `codebase-explorer` subagent | [Cursor](docs/user-guide/platforms/cursor.md) |
| **Claude Code** | `.mcp.json`, a `CLAUDE.md` block, a Haiku `codebase-explorer` subagent | [Claude Code](docs/user-guide/platforms/claude-code.md) |
| **VS Code (Copilot)** | `.vscode/mcp.json`, a `copilot-instructions.md` block | [VS Code](docs/user-guide/platforms/vscode-copilot.md) |
| **Codex** | an `AGENTS.md` block, plus the command to register the server | [Codex](docs/user-guide/platforms/codex.md) |
| Antigravity, Windsurf, Claude Desktop, Zed, Cline, … | `codebase-index config` prints the JSON to paste | [Other clients](docs/user-guide/platforms/other-clients.md) |

`setup` merges into existing files (your other MCP servers and your own instructions are kept), is safe to
re-run, and `--dry-run` shows what it would do.

---

## Documentation: find what is for you

| You are... | Start here |
|---|---|
| **A user** who wants it working | [Quick start](docs/user-guide/quick-start.md) → your [editor guide](docs/user-guide/platforms/cursor.md) → [Using it day to day](docs/user-guide/using-it.md) |
| **Stuck** | [Troubleshooting](docs/user-guide/troubleshooting.md) · [FAQ](docs/user-guide/faq.md) |
| **Curious** how it works or why it saves tokens | [Token savings](docs/concepts/token-savings.md) · [How it works](docs/concepts/how-it-works.md) |
| **Looking something up** | [Tools reference](docs/reference/tools.md) · [Command line](docs/reference/cli.md) · [Configuration](docs/user-guide/configuration.md) |
| **A contributor** | [Contributing](CONTRIBUTING.md) · [Add a language or client](docs/developers/extending.md) |

Everything is indexed in **[docs/README.md](docs/README.md)**.

---

## What the assistant can do with it

| Tool | Answers |
|---|---|
| `repo_map` | Main folders and the most important files |
| `search_symbol` | Where is X defined? |
| `get_file_summary` / `get_exports` | A file's outline / its public API, with line numbers |
| `read_symbol_source` | Exact code of one function or class (huge ones come back folded) |
| `find_callers` / `find_callees` | Who calls X (and what breaks) / what X calls |
| `who_imports` | Which files depend on this file |
| `find_route` | Which handler serves `/api/...` (FastAPI, Flask, Express) |
| `summarize_file` | Intent of one file via a cheap model (optional, needs an API key) |
| `reindex`, `index_stats` | Maintenance |

Examples of real output and every argument: [Tools reference](docs/reference/tools.md).

## Limits to know about

- `find_callers` matches by **name**, so verify before big refactors (it shows the receiver and warns on duplicates).
- Only static imports are resolved; computed `import()` strings are not.
- The index knows structure, not runtime behaviour or types.
- Unsaved editor changes are invisible: save before asking.
- Markdown, SQL, YAML and JSON are not indexed; assistants read them normally.

## Privacy

Everything except the optional `summarize_file` runs locally with no network calls. `summarize_file` sends
one file to the provider whose API key you set; leave the keys empty to stay fully offline.

## Contributing and license

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports:
[SECURITY.md](SECURITY.md). Licensed under [MIT](LICENSE).
