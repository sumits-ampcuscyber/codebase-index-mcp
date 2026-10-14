# Security policy

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private vulnerability reporting
("Security" tab → "Report a vulnerability") on this repository, or email the maintainer listed in the
repository profile. You will get an answer within a few days.

## Scope and design notes

- The server runs locally over stdio and makes **no network calls**, except `summarize_file`, which sends one
  file (or line range) to the provider whose API key you configured.
- It only reads files inside the configured repo root (`CODEBASE_ROOT`) and writes only to
  `<repo>/.codebase-index/`.
- Tools only read files that are in the index (git-tracked, or unignored supported source files inside the
  repo). Arbitrary files such as `.env` cannot be read through `read_symbol_source` or sent out by
  `summarize_file`.
- Symlinks that resolve outside the repo and non-regular files are skipped while indexing. The index folder
  is refused if it is a symlink.
- git runs with `core.fsmonitor=false` and `safe.bareRepository=explicit`, so a repo's own `.git/config`
  cannot make the indexer run commands.
- API keys come from the environment or `.env` files and are never logged or stored in the index.
- `codebase-index setup` writes only inside the workspace. It refuses to write through symlinks that leave
  the workspace, and it never edits global client configs. Git hook lines are shell-quoted.

Treat answers from the index as untrusted data when the repo itself is untrusted: file contents and
docstrings can contain text that tries to instruct the agent (prompt injection).
