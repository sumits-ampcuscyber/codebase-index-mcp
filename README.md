# codebase-index-mcp

A local MCP server that gives your coding agent (Cursor, Claude Code, Codex, Antigravity, …) a
**structural index of your repo**, so it can answer "where is X / what calls X / show me X" from a few
hundred tokens of exact facts instead of reading whole files into the model's context.

- **Parser, not LLM**: tree-sitter → SQLite. Indexing is free, local, and incremental.
- **Compact answers**: every tool returns dense plain text (one fact per line), not pretty JSON.
- **Always fresh**: a watcher re-indexes changed files every 2 s; git hooks optional.
- **Optional cheap model** (`summarize_file`) and a **Cursor subagent** (Grok 4.7 by default) for
  "how does this work?" questions, so the expensive main model never sees raw source.

Languages: **Python, JavaScript/JSX, TypeScript/TSX**. See [docs/GUIDE.md](docs/GUIDE.md#9-adding-a-language) to add more.

---

## Why: measured on a real 749-file repo (Python + React/TS, 204k lines)

| Question | Without the index | With the index |
|---|---|---|
| Outline of a 5,195-line component file | read file: ~64,000 tokens | `get_file_summary`: ~2,700 |
| Code of a 4,028-line React component | read file (the old tool returned only its first 300 lines) | `read_symbol_source`: folded skeleton ~2,300, then only the parts you need |
| Where is anything named `get`? | grep + opening files | `search_symbol`: ~710 (was ~1,230 as pretty JSON) |
| Orientation in an unfamiliar repo | several `ls` / Glob / Read turns | `repo_map`: ~900 |

Full index: 3.3 s for 749 files (was 10.9 s); re-check when nothing changed: 0.16 s.
Token counts are ≈ characters ÷ 4. Tool output is also re-sent on every later turn of the chat,
so savings compound.

---

## Tools

| Tool | Answers | Cost |
|---|---|---|
| `repo_map` | Main folders + most-imported files and their key symbols (PageRank on the import graph) | free |
| `search_symbol` | Where is X defined? `Class.method`, `Class.` (members), `accept evidence` (matches `acceptEvidence` / `accept_evidence`), `a, b, c` (batch) | free |
| `get_file_summary` | File outline: imports, HTTP routes, symbols with line ranges, signatures, first docstring line | free |
| `get_exports` | Public API of a file | free |
| `read_symbol_source` | Exact code of one or more symbols (file optional if unique). Huge symbols → **folded skeleton** with line ranges to drill into | free |
| `find_callers` | Call sites grouped by file, with enclosing function and receiver; `depth=2..3` for callers-of-callers (impact) | free |
| `find_callees` | What a function/class calls, resolved to project definitions | free |
| `who_imports` | Which files import this file (resolved: relative paths, tsconfig `paths`, Python packages), and what it imports | free |
| `find_route` | Which handler serves `/api/...` (FastAPI/Flask decorators, Express `router.get`) | free |
| `summarize_file` | Intent of ONE file via a cheap model (Gemini Flash / Claude Haiku). Cached | small API call |
| `reindex`, `index_stats` | Maintenance / health | free |

---

## Quick start

**Needs:** Python 3.10+ and git.

### 1. Get the code and install

```bash
git clone https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
cd codebase-index-mcp
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Put the folder next to your project (`workspace/your-repo` + `workspace/codebase-index-mcp`) or inside
it. It never indexes itself.

### 2. Point it at your repo and build the index

```bash
# only needed when the tool folder is NOT inside the repo
export CODEBASE_ROOT=/absolute/path/to/your-repo           # macOS/Linux
$env:CODEBASE_ROOT = "C:\absolute\path\to\your-repo"       # Windows PowerShell

python cli.py index
python cli.py map          # sanity check: you should see your folders and key files
```

You can also put `CODEBASE_ROOT=...` in `codebase-index-mcp/.env` (copy `.env.example`).

### 3. Connect your agent

**Cursor**: one command, with the venv active:

```bash
python setup_cursor.py
```

It writes (merging with what is already there) into `<your-repo>/.cursor/`:

| File | Purpose |
|---|---|
| `mcp.json` | the MCP server entry (venv Python + absolute paths) |
| `rules/codebase-index.mdc` | always-on rule: use the index before reading files |
| `agents/codebase-explorer.md` | read-only subagent for multi-file questions, **pinned to Grok 4.7** |

Restart Cursor (or toggle the server under *Settings → MCP*).

**Claude Code**:

```bash
python print_mcp_config.py --claude     # prints a ready `claude mcp add ...` command; run it in your repo
```

Then append [`rules/AGENTS.snippet.md`](rules/AGENTS.snippet.md) to your repo's `CLAUDE.md`.

**Codex / Antigravity / any MCP client**: `python print_mcp_config.py` prints the `mcpServers` JSON.
Paste it into the client's config (Antigravity: `~/.gemini/antigravity/mcp_config.json`) and append
[`rules/AGENTS.snippet.md`](rules/AGENTS.snippet.md) to `AGENTS.md` (or `GEMINI.md`).

The server also sends a short routing guide as MCP *instructions*, so clients that show server
instructions to the model know when to use each tool without any rule file.

### 4. Try it

Ask: *"Use the codebase index to find the class that handles X and show its public methods."* You
should see `search_symbol` / `get_file_summary` / `read_symbol_source` calls instead of whole-file
reads. For *"How does X work end to end?"* in Cursor, you should see the `codebase-explorer` subagent.

---

## Cursor subagent model (default: Grok 4.7)

Multi-file "how does this work" questions are delegated to the `codebase-explorer` subagent, which runs
on a fast, cheap model and returns a short written answer, so the raw source never enters your main chat.
**It runs on `grok-4.7` by default.** To change it, use any one of these:

```bash
python setup_cursor.py --model <model-id>          # rewrites .cursor/agents/codebase-explorer.md
```

- or set `CURSOR_SUBAGENT_MODEL=<model-id>` in `codebase-index-mcp/.env`, then re-run `python setup_cursor.py`
- or edit the `model:` line in `<your-repo>/.cursor/agents/codebase-explorer.md` directly

Use the model id exactly as Cursor's model picker lists it. `inherit` (same model as the main chat) and
`fast` also work. More detail: [docs/GUIDE.md § Subagents](docs/GUIDE.md#6-cursor-subagent-and-model-choice).

---

## Optional: cheap-model key for `summarize_file`

Copy `.env.example` to `.env` and set **one** of:

| Variable | Provider | Default model | Extra install |
|---|---|---|---|
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | Google Gemini | `gemini-2.5-flash` | none |
| `ANTHROPIC_API_KEY` | Anthropic | `claude-haiku-4-5` | `pip install anthropic` |

Override with `CHEAP_MODEL_PROVIDER=gemini|anthropic` and `CHEAP_MODEL=<model>`. Answers are cached by
(file content + line range + question + model). Without a key every other tool still works, and
`summarize_file` returns a clear "no key" message instead of failing.

## Optional: git hooks

```bash
python install_git_hooks.py              # refresh after commit / checkout / merge / rebase
python install_git_hooks.py --uninstall
```

The watcher already covers this while the MCP server runs; hooks keep the index fresh when it is not.

---

## Configuration

Set in `codebase-index-mcp/.env` or in the MCP config `env` block (the environment wins over `.env`).

| Variable | Default | Purpose |
|---|---|---|
| `CODEBASE_ROOT` | git root of the tool folder, else of cwd | Absolute path of the repo to index |
| `CODEBASE_WATCH_INTERVAL` | `2` | Seconds between background re-scans; `0` = off |
| `CODEBASE_MAX_FILE_BYTES` | `1000000` | Skip larger files |
| `CODEBASE_EXCLUDE_DIRS` | none | Extra folder names to skip (comma-separated) |
| `CODEBASE_INDEX_WORKERS` | CPUs − 1 (max 8) | Parser processes for big (2,000+ file) index runs; `1` = in-process |
| `CURSOR_SUBAGENT_MODEL` | `grok-4.7` | Model written into the Cursor subagent by `setup_cursor.py` |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` | none | Enable `summarize_file` |
| `CHEAP_MODEL_PROVIDER`, `CHEAP_MODEL` | auto | Pick provider / model for `summarize_file` |

Always skipped: `node_modules`, `.venv`, `venv`, `dist`, `build`, `.next`, `__pycache__`, `.git`,
`coverage`, the index folder itself, and anything in `.gitignore`.
The index lives in `<your-repo>/.codebase-index/index.db` (the folder git-ignores itself).

---

## CLI

```text
python cli.py index [--full]                  build / refresh
python cli.py stats
python cli.py map [path]
python cli.py search "UserService, accept evidence"
python cli.py summary path/to/file.py [--depth 2]
python cli.py exports path/to/file.py
python cli.py source UserService.save [--file path] [--mode skeleton]
python cli.py callers save [--receiver repo] [--depth 2]
python cli.py callees UserService.save
python cli.py importers path/to/file.py
python cli.py routes /users [--method GET]
python cli.py ask path/to/file.py "what does this do?"   # cheap model; needs a key
```

---

## Known limits

- **Name-based call graph.** `find_callers` matches by function name (with the receiver shown to help);
  it warns when several definitions share a name. Verify before large refactors.
- **Static imports only.** Dynamic `import()`/`importlib` with computed strings, and aliases the
  resolver cannot map, are not in `who_imports`.
- **Route prefixes** from `include_router(..., prefix=)` / `app.use("/api", router)` are not added; the
  router's own `APIRouter(prefix=...)` is.
- **No types or semantics.** That is what `summarize_file` / the subagent are for.
- **Unsaved editor buffers** are invisible: save before asking.
- Non-code files (Markdown, SQL, YAML, JSON…) are not indexed; agents read them normally.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tools missing in the client | `command` must be the **venv** Python; restart the client / toggle MCP |
| Server shows an error | Run `python mcp_server.py` in the venv and read the traceback (usually a missing `pip install`) |
| Wrong repo in `index_stats` | Set `CODEBASE_ROOT` in the MCP `env` block (or `.env`) |
| "not in the index" | Unsupported type, git-ignored, over the size limit, or a wrong path |
| "ambiguous" | Pass a longer path from the listed candidates |
| Subagent model not found in Cursor | Use the exact id from Cursor's model picker: `python setup_cursor.py --model <id>` |
| Want a clean rebuild | `python cli.py index --full` (or delete `.codebase-index/`) |

## Development

```bash
python -m unittest discover -s tests -v
```

Architecture, data model, token economics and how to add a language: **[docs/GUIDE.md](docs/GUIDE.md)**.

## License

[MIT](LICENSE)
