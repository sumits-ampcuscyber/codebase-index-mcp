# Troubleshooting

**First step, always:** run `codebase-index doctor` in your repo. It checks Python and dependencies, the
repo root, the index, and whether each client's config points at a Python that exists.

## Install problems

| Symptom | Fix |
|---|---|
| `codebase-index: command not found` | Close and reopen the terminal. If still missing, run `python -m pipx ensurepath` and reopen again. On Windows, check that Python's `Scripts` folder is on PATH |
| `pipx: command not found` | `python -m pip install --user pipx`, then `python -m pipx ensurepath`, then reopen the terminal |
| `python` not found / version too old | Install Python 3.10+ from python.org (Windows: tick "Add Python to PATH"). On macOS/Linux try `python3` |
| pipx cannot download from GitHub | Check network/proxy and that the repository is public or you are logged in to git. Alternative: [install from a clone](install.md#from-a-clone-development-or-vendoring-into-a-repo) |
| Build errors for tree-sitter | Use Python 3.10-3.13 (prebuilt wheels exist); upgrade pip: `python -m pip install -U pip` |

## Connection and setup

| Symptom | Likely cause → fix |
|---|---|
| Tools missing in the client | The client was not restarted, or the MCP entry is not loaded. Restart / toggle the server (Cursor: Settings → MCP; Claude Code: `/mcp`; VS Code: MCP: List Servers) |
| Server shows an error or times out | Run `python -m codebase_index.server` with the same Python the config uses and read the traceback (usually a missing dependency). On a huge repo run `codebase-index index` once first |
| `command not found` / `No such file` in the client log | The venv or pipx environment was moved or deleted. Re-run `codebase-index setup <client>` from an environment where the package is installed |
| `No module named codebase_index` | The config's Python does not have the package. Reinstall into that Python, or re-run `setup` with the right one |
| `No module named mcp.server.mcpserver` | You have MCP SDK 1.x. This tool needs `mcp>=2.2,<3`: `pip install -U "mcp>=2.2,<3"` |
| Wrong repo in answers | `index_stats` shows the root. Set `CODEBASE_ROOT` in the config's `env` block |
| Tools appear but the agent ignores them | Install the rule/instruction file (`setup` does), and ask structurally ("find where X is defined using the index") |

## Results

| Symptom | Likely cause → fix |
|---|---|
| "not in the index" | Unsupported extension, git-ignored, over `CODEBASE_MAX_FILE_BYTES`, or a wrong path |
| "ambiguous" | Pass a longer path from the listed candidates |
| Recent edit not visible | The file is unsaved, or the watcher is off (`CODEBASE_WATCH_INTERVAL=0`). Save, or call `reindex` |
| A symbol or call is missing | The language construct is not extracted ([how-it-works](../concepts/how-it-works.md#what-the-parser-extracts)). Open an issue with a minimal snippet |
| `find_callers` shows unrelated callers | Name-based matching. Use `receiver=` to filter, or check the files listed |
| Want a clean rebuild | `codebase-index index --full`, or delete `.codebase-index/` |

## Platform-specific

| Symptom | Fix |
|---|---|
| Cursor: subagent model not found | Use the exact id from Cursor's model picker: `codebase-index setup cursor --model <id>` |
| Windows: paths with spaces | Fine: `setup` writes absolute paths as JSON strings. If you edit by hand, use double backslashes or forward slashes |
| Windows: hook does nothing | Re-run `codebase-index hooks`; hooks use a detached process because plain `&` jobs die in Git Bash |
| `summarize_file` says "no API key" | Expected without a key. Set `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` ([configuration](configuration.md)) or use `read_symbol_source` instead |
| Anthropic summaries fail with an import error | `pip install anthropic` into the same environment |

## Known limits

- **Name-based call graph.** `find_callers` matches by function name; it shows the receiver and warns on duplicates.
- **Static imports only.** Dynamic `import()` / `importlib` with computed strings, and aliases the resolver cannot map, are not in `who_imports`.
- **Route prefixes** from `include_router(..., prefix=)` / `app.use("/api", router)` are not added; the router's own `APIRouter(prefix=...)` is.
- **No types or semantics.** That is what `summarize_file` and the subagents are for.
- **Unsaved editor buffers** are invisible.
- **Three languages today:** Python, JavaScript/JSX, TypeScript/TSX ([add one](../developers/extending.md)).

Still stuck? [Open an issue](https://github.com/sumits-ampcuscyber/codebase-index-mcp/issues) and paste the output
of `codebase-index doctor` (it contains paths, so redact if needed).
