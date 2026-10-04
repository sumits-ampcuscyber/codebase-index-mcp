# Contributing

Thanks for helping! Bug reports, new languages and new client setups are all welcome.

## Dev setup

```bash
git clone https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
cd codebase-index-mcp
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[anthropic]"
python -m unittest discover -s tests -v
```

CI runs the tests on Linux, macOS and Windows with Python 3.10 and 3.13.

## Layout

```text
src/codebase_index/   indexer.py (parse + store)  queries.py (answers)  server.py (MCP)
                      cli.py  clients.py (setup)  doctor.py  bench.py  hooks.py  config.py
                      templates/ (rule, instruction and subagent files that `setup` installs)
tests/                end-to-end tests on a synthetic repo, and setup/template tests
docs/                 user and platform guides; how-it-works
```

See [docs/how-it-works.md](docs/how-it-works.md) for the architecture and [docs/extending.md](docs/extending.md)
for adding a language or a client.

## Guidelines

- **Output stays compact.** Tool answers are plain text, one fact per line. Before adding a field, ask whether
  an agent needs it; every character is paid for on every later turn. Keep the tool list small too: each tool
  definition costs tokens in every session.
- **Stdout belongs to MCP.** In the server, never `print()` to stdout; log to stderr.
- **Parsers, not guesses.** Prefer tree-sitter facts over regexes. Add a test fixture for every new construct.
- **Setup is safe.** `setup` must merge, be idempotent, honour `--dry-run`, and never touch files outside the
  workspace.
- Match the surrounding style; keep functions small and comments rare and useful.
- Update the docs and `CHANGELOG.md` with the change.

## Pull requests

1. Open an issue first for anything large.
2. Add or update tests; run the suite.
3. Describe what changed and why, and paste `codebase-index bench` output if you touched output formats.
