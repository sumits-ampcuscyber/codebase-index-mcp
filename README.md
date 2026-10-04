# codebase-index-mcp

**Give your coding agent a map of your repo, so it stops reading whole files.**

A local [MCP](https://modelcontextprotocol.io) server that parses your code with tree-sitter into a
SQLite index and answers *"where is X / what calls X / show me X"* with a few hundred tokens of exact
facts, instead of the thousands an agent spends opening files. Works with **Cursor, Claude Code,
OpenAI Codex, VS Code (Copilot)**, and any other MCP client.

- **A parser, not an LLM.** Indexing is free, local, offline and incremental.
- **Compact answers.** Dense plain text, one fact per line; huge functions come back as a folded skeleton.
- **Always fresh.** A background watcher re-indexes changed files within seconds.
- **Optional cheap model.** `summarize_file` (Gemini Flash / Claude Haiku) and a pinned subagent (Cursor,
  Claude Code) answer "how does this work?" without the expensive main model ever seeing raw source.

Languages: **Python, JavaScript / JSX, TypeScript / TSX** ([add more](docs/extending.md)).

## What it saves

Measured on a real 749-file Python + React/TypeScript repo (204k lines):

| Question | Read the file(s) | With the index |
|---|---|---|
| Outline of a 5,195-line component | ~64,000 tokens | `get_file_summary` ~2,700 |
| Code of a 4,028-line component | ~50,000 tokens | skeleton ~2,300, then only the ranges you need |
| Where is anything named `get`? | grep + opening files | `search_symbol` ~710 |
| Orientation in an unfamiliar repo | several `ls` / Glob / Read turns | `repo_map` ~900 |

Tokens ≈ characters ÷ 4. Tool output is re-sent on every later turn, so savings compound. Run
`codebase-index bench` to see the numbers for **your** repo. Details and honest overhead:
[docs/token-savings.md](docs/token-savings.md).

## Install

Needs Python 3.10+ and git.

```bash
pipx install git+https://github.com/sumits-ampcuscyber/codebase-index-mcp.git    # or: uv tool install ...
```

Other ways (pip in a venv, clone for development, Windows notes): [docs/install.md](docs/install.md).

## Set up your agent (60 seconds)

In your project folder (the git repo you want indexed):

```bash
cd /path/to/your-repo
codebase-index setup cursor        # or: claude-code | vscode | codex | all
codebase-index doctor              # checks that everything is wired correctly
```

| Client | What `setup` writes | Guide |
|---|---|---|
| **Cursor** | `.cursor/mcp.json`, an always-on rule, a read-only `codebase-explorer` subagent (Grok 4.7 by default) | [docs/platforms/cursor.md](docs/platforms/cursor.md) |
| **Claude Code** | `.mcp.json`, a block in `CLAUDE.md`, a read-only `codebase-explorer` subagent (Haiku by default) | [docs/platforms/claude-code.md](docs/platforms/claude-code.md) |
| **VS Code (Copilot)** | `.vscode/mcp.json`, a block in `.github/copilot-instructions.md` | [docs/platforms/vscode-copilot.md](docs/platforms/vscode-copilot.md) |
| **Codex** | a block in `AGENTS.md`; prints the `codex mcp add` command (global config is yours to edit) | [docs/platforms/codex.md](docs/platforms/codex.md) |
| Antigravity, Windsurf, Claude Desktop, Zed, Cline, … | `codebase-index config` prints generic `mcpServers` JSON | [docs/platforms/other-clients.md](docs/platforms/other-clients.md) |

`setup` merges into existing files (your other MCP servers and your own instructions are kept), is safe to
re-run, and `--dry-run` shows what it would change. Then restart the client and ask:

> *"Use the codebase index to find the class that handles X and show its public methods."*

You should see `search_symbol` / `get_file_summary` / `read_symbol_source` calls instead of whole-file reads.

## Tools

| Tool | Answers |
|---|---|
| `repo_map` | Main folders and the most-imported files with key symbols |
| `search_symbol` | Where is X defined? (`Class.method`, `Class.`, `two words`, `a, b, c`) |
| `get_file_summary` / `get_exports` | A file's outline with line ranges, signatures, first docstring line / its public API |
| `read_symbol_source` | Exact code of one or more symbols; huge ones as a folded skeleton |
| `find_callers` / `find_callees` | Call sites (`depth=2` for impact) / what a function calls |
| `who_imports` | Which files import this file (resolves relative paths, tsconfig `paths`, Python packages) |
| `find_route` | Which handler serves `/api/...` (FastAPI, Flask, Express) |
| `summarize_file` | Intent of ONE file via a cheap model (optional, needs an API key) |
| `reindex`, `index_stats` | Maintenance |

Full reference with example output: [docs/tools.md](docs/tools.md).

## Command line

The same queries work in a terminal: `codebase-index map`, `search`, `summary`, `source`, `callers`, …
Run `codebase-index --help`. Handy extras: `doctor` (diagnose), `bench` (tokens saved on your repo),
`hooks` (refresh the index after git commit/checkout).

## Documentation

| | |
|---|---|
| [Install](docs/install.md) | pipx / uv / pip / clone, upgrading, uninstalling |
| [Platform guides](docs/platforms/) | Cursor, Claude Code, VS Code, Codex, others |
| [Token savings](docs/token-savings.md) | Where the savings come from, overhead, how to get the most |
| [How it works](docs/how-it-works.md) | Architecture, stack, data model, freshness, performance, privacy |
| [Tools reference](docs/tools.md) | Every tool, its arguments and output format |
| [Configuration](docs/configuration.md) | Environment variables, `.env`, exclusions, multiple repos |
| [Troubleshooting](docs/troubleshooting.md) | Symptoms and fixes, known limits |
| [Extending](docs/extending.md) | Add a language |
| [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) | |

## Known limits

- **Name-based call graph.** `find_callers` matches by function name (it shows the receiver and warns on
  duplicates). Verify before large refactors.
- **Static imports only.** Computed `import()` / `importlib` strings are not resolved.
- **No types or semantics.** That is what `summarize_file` and the subagents are for.
- **Unsaved editor buffers** are invisible: save before asking.
- Markdown, SQL, YAML, JSON and other non-code files are not indexed; agents read them normally.

## Privacy

Everything except `summarize_file` runs locally and makes no network calls. `summarize_file` sends one
file (or line range) to the provider whose API key you configure; leave the keys empty to stay fully offline.

## License

[MIT](LICENSE)
