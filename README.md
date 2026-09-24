# codebase-index-mcp

A drop-in MCP server that lets your coding agent answer structural questions about a repo from
a local index — instead of reading whole files into the main model's context.

| Layer | What it does | Cost |
|---|---|---|
| **Parser + index** (tree-sitter → SQLite) | Where is X, what's in this file, who calls X, who imports this file, exact source of one function | ~0 tokens, milliseconds |
| **Cheap model** (`summarize_file`) | Optional single-file "what does this do?" via Gemini Flash or Claude Haiku | Small API call, cached |
| **Cursor subagent** (rule-guided) | Multi-file / end-to-end intent when you use Cursor (or when no API key is set) | Cursor plan usage on a fast model |

Your IDE's main (expensive) model sees short JSON answers, not raw source. A rule file tells the
agent to use the free tools first.

**Languages:** Python, JavaScript/JSX, TypeScript, TSX. ([Add more](docs/GUIDE.md#8-adding-another-language).)

**Deep dive:** [docs/GUIDE.md](docs/GUIDE.md) — architecture, token savings, intent routing, data model.

---

## Why (token savings)

Agents bill for **input** tokens. Opening a ~3,000-line service file can put ~29,000 tokens into
the main context; `get_exports` on the same file is ~1,200 tokens; locating a symbol with
`search_symbol` is often ~50–100. Those savings compound because earlier tool results are resent
on later turns. See [How it reduces input token cost](docs/GUIDE.md#2-how-it-reduces-input-token-cost).

---

## What's in the folder

```
codebase-index-mcp/
  mcp_server.py          MCP server (what the IDE launches)
  indexer.py             tree-sitter + SQLite + incremental sync
  queries.py             lookups behind each free tool
  cheap_delegate.py      optional cheap-model call + cache
  cli.py                 build/refresh index; try queries in a terminal
  install_git_hooks.py   refresh after commit/checkout/merge/rebase
  refresh_detached.py    non-blocking hook refresh (Windows-safe)
  print_mcp_config.py    prints MCP JSON with absolute paths
  requirements.txt
  .env.example
  rules/
    cursor-codebase-graph.mdc   Cursor rule template
    AGENTS.snippet.md           for AGENTS.md (Cursor / Claude Code / Codex / Antigravity)
  docs/
    GUIDE.md                    architecture and token-cost deep dive
```

Index DB: `<your-repo>/.codebase-index/index.db` (folder self-gitignores).

---

## Quick start (Cursor)

**Needs:** Python 3.10+, git.

### 1. Place the folder

Preferred (tool next to the code):

```
workspace/
  your-repo/              <- CODEBASE_ROOT
  codebase-index-mcp/    <- this folder
```

You can also put it inside `your-repo/`. It never indexes itself.

### 2. Venv and install

Windows (PowerShell):

```powershell
cd path\to\codebase-index-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux:

```bash
cd path/to/codebase-index-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Build the index

If the tool sits **outside** the repo, set the root for this session:

```powershell
$env:CODEBASE_ROOT = "C:\absolute\path\to\your-repo"   # Windows
# export CODEBASE_ROOT=/absolute/path/to/your-repo     # macOS/Linux
python cli.py index
python cli.py stats
```

### 4. Wire Cursor

With the venv active:

```powershell
python print_mcp_config.py --cursor
```

Save as `<workspace>/.cursor/mcp.json` (or merge into an existing `mcpServers` object). Copy
`rules/cursor-codebase-graph.mdc` to `.cursor/rules/`. Restart MCP (or Cursor) so tools appear.

### 5. Optional: cheap-model key for `summarize_file`

```powershell
copy .env.example .env   # or: cp .env.example .env
```

Set **one** of `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`. Without a key, free tools still work;
intent questions should use a Cursor explore subagent (see the rule), not full-file reads.

### 6. Optional: git hooks

```powershell
python install_git_hooks.py
```

Undo: `python install_git_hooks.py --uninstall`.

### 7. Try it

Ask Cursor to use the codebase-index tools to find a class and list its exports. You should see
`search_symbol` / `get_exports`, not large file opens. For "how does X work end to end?", you
should see an explore subagent (fast model) rather than dumping several full files into chat.

---

## Other clients (Antigravity, Claude Code, Codex)

```powershell
python print_mcp_config.py
```

Paste into the client's MCP config (Antigravity: `~/.gemini/antigravity/mcp_config.json`).
Append `rules/AGENTS.snippet.md` to `AGENTS.md` at the repo root (or `GEMINI.md` for Antigravity
only). Those clients do not have Cursor subagents: with no API key, the snippet says to use
`read_symbol_source` on the relevant function — not the whole file.

---

## Tools

| Tool | Question | Cost |
|---|---|---|
| `search_symbol` | Where is X? (`Class.method`, optional `kind`) | Free |
| `get_file_summary` | What's in this file? | Free |
| `get_exports` | Public API of a file | Free |
| `find_callers` | Who calls this name? | Free |
| `who_imports` | Who imports this file? | Free |
| `read_symbol_source` | Exact source of one function/class | Free |
| `summarize_file` | Intent for **one** file (needs API key) | Cheap API |
| `reindex` | Force refresh | Free |
| `index_stats` | Health check | Free |

### Routing

| Question | Prefer | Cost |
|---|---|---|
| Where / shape / callers / imports / one function's code | Tools 1–4 above | Free |
| Intent, **one** file, key configured | `summarize_file` | Cheap API |
| Intent, multi-file / end-to-end, or no key (Cursor) | explore subagent, fast model | Cursor plan |
| Intent, no key (other agents) | `read_symbol_source` on the relevant function | Free |

After a no-key error from `summarize_file`, stop calling it for the rest of that chat.

---

## Daily use

- While the MCP server runs, a watcher re-indexes every few seconds (`CODEBASE_WATCH_INTERVAL`,
  default 2). Saves, new files, deletes, branch switches, and pulls are picked up without a
  full rebuild.
- Every tool call also refreshes if the watch has not just done so.
- Git hooks (if installed) refresh after commit / checkout / merge / rebase.
- Blind spot: **unsaved** editor buffers — save before asking the agent to plan.
- `summarize_file` answers are cached by (file content + question + model).

---

## Configuration

Set in `codebase-index-mcp/.env` or in the MCP config `env` block. Environment wins over `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `CODEBASE_ROOT` | Git root of tool / cwd / parent | Absolute path of the repo to index |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | — | Enable `summarize_file` via Gemini |
| `ANTHROPIC_API_KEY` | — | Enable `summarize_file` via Anthropic |
| `CHEAP_MODEL_PROVIDER` | Auto from key | `gemini` or `anthropic` |
| `CHEAP_MODEL` | Flash / Haiku defaults | Override model name |
| `CODEBASE_WATCH_INTERVAL` | `2` | Seconds between watches; `0` = off |
| `CODEBASE_MAX_FILE_BYTES` | `1000000` | Skip larger files |
| `CODEBASE_EXCLUDE_DIRS` | — | Extra comma-separated folder names |

Built-in excludes include `node_modules`, `.venv`, `dist`, `build`, `.codebase-index`, and similar.

---

## Known limits

- **Name-based** `find_callers` — ambiguous names get a warning; verify before refactors.
- **`who_imports`** matches by module-path suffix; aliases / re-exports / dynamic imports can be missed.
- **No types or meaning** in the parser — that's what `summarize_file` / a subagent are for.
- Files **over 1 MB** skipped; raise `CODEBASE_MAX_FILE_BYTES` if needed.
- Only listed extensions are indexed; Markdown/SQL/YAML/etc. are read normally.
- Routing is **rule-guided**, not enforced.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tools missing in Cursor | `command` must be the **venv** Python; toggle MCP or restart Cursor |
| Server errored | Run `python mcp_server.py` in the venv; fix traceback (often missing pip install) |
| Wrong repo in `index_stats` | Set `CODEBASE_ROOT` in MCP `env` |
| `summarize_file` no API key | Fill `.env`, restart MCP — or use a Cursor explore subagent / `read_symbol_source` |
| File "not in the index" | Unsupported type, gitignored, too large, or bad path |
| Path "ambiguous" | Pass a fuller path from `candidates` |
| Want a clean rebuild | Delete `.codebase-index/` or `python cli.py index --full` |

---

## CLI

```text
python cli.py index [--full]
python cli.py stats
python cli.py search MyClass
python cli.py summary path/to/file.py
python cli.py exports path/to/file.py
python cli.py callers my_func
python cli.py importers path/to/file.py
```

---

## More

- [docs/GUIDE.md](docs/GUIDE.md) — architecture diagrams, token economics, subagent vs API,
  freshness, ER diagram, layouts, adding languages.
