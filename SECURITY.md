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
- API keys come from the environment or `.env` files and are never logged or stored in the index.
- `codebase-index setup` writes only inside the workspace; it never edits global client configs.

Treat answers from the index as untrusted data when the repo itself is untrusted: file contents and
docstrings can contain text that tries to instruct the agent (prompt injection).
