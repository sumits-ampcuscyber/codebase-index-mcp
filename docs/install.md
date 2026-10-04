# Install

**Requirements:** Python 3.10+ and git (git is optional but recommended: it makes the indexer respect
`.gitignore`). Works on Windows, macOS and Linux.

## Recommended: pipx or uv (one global install, any repo)

```bash
pipx install git+https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
# or
uv tool install git+https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
```

This puts `codebase-index` on your PATH in its own isolated environment. Then, inside any repo:

```bash
cd /path/to/your-repo
codebase-index setup cursor      # or claude-code | vscode | codex | all
codebase-index doctor
```

The generated MCP config points at the Python of that isolated environment, so the client does not need
anything on its PATH.

> Once the package is published to PyPI this becomes `pipx install codebase-index-mcp`.

## pip in a virtual environment

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install git+https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
codebase-index doctor
```

Always run `codebase-index setup ...` with the environment active: the config records that environment's
Python. If you later delete or move the environment, re-run `setup`.

## From a clone (development, or vendoring into a repo)

```bash
git clone https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
cd codebase-index-mcp
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[anthropic]"                          # drop the extra if you use Gemini or no key
```

A clone placed **inside** the repo you want indexed (`your-repo/codebase-index-mcp/`) works too: it finds
the enclosing git root and never indexes itself. A clone **next to** it needs `CODEBASE_ROOT` (the setup
command writes it for you when you run it from the target repo).

## Check it works

```bash
codebase-index index        # builds .codebase-index/index.db (3 s for ~750 files)
codebase-index map          # you should see your folders and key files
codebase-index bench        # tokens saved vs reading files, on your repo
```

## Optional extras

| Want | Do |
|---|---|
| `summarize_file` (cheap-model summaries) | Put `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` in `~/.codebase-index.env` ([configuration](configuration.md)). Anthropic also needs `pip install anthropic` (or `pipx inject codebase-index-mcp anthropic`) |
| Index refresh after `git commit/checkout/merge` when no agent is running | `codebase-index hooks` (remove with `--uninstall`) |

## Upgrade / uninstall

```bash
pipx upgrade codebase-index-mcp              # or: uv tool upgrade codebase-index-mcp
pipx uninstall codebase-index-mcp
```

The index lives in `<your-repo>/.codebase-index/` (it git-ignores itself); delete that folder to remove it.
Generated client files are plain files: delete `.cursor/mcp.json` entries, the
`<!-- codebase-index:start -->` … `<!-- codebase-index:end -->` block in `CLAUDE.md` / `AGENTS.md` /
`.github/copilot-instructions.md`, and the `codebase-explorer.md` agent files.
