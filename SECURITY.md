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
- Symlinks and Windows junctions are refused in **every** path component, including links that stay inside
  the repo (an in-repo link could alias an ignored secret, e.g. `visible.py -> .env`). Only regular files are
  read; FIFOs and devices are skipped. The index folder and database are refused if they are symlinks.
- On Linux/macOS each file is opened component by component with `O_NOFOLLOW` relative to the already-checked
  parent directory, and type and size are checked on the same descriptor that is read, so the check cannot
  be raced. Windows has no `openat`, so the path is checked, opened, and the opened file's id compared with
  the checked one; a swap in between is refused.
- `.git/HEAD`, `commondir` and refs are read only to show the current commit: only a well-formed `refs/...`
  name is followed and only a commit id is ever returned.
- git is run by absolute path, found only in absolute `PATH` entries outside the repo. A bare `git` (and
  `shutil.which`) on Windows also searches the current folder, where MCP clients start the server, so a
  repo could otherwise ship its own `git.exe`.
- git runs with `core.fsmonitor=false` and `safe.bareRepository=explicit`, so a repo's own `.git/config`
  cannot make the indexer run commands.
- API keys come from the environment or `.env` files and are never logged or stored in the index. The
  repo being indexed cannot supply them: only the process environment, `CODEBASE_INDEX_ENV`, this tool's own
  `.env` and `~/.codebase-index.env` are read. Any key in the server's environment enables `summarize_file`,
  so set `CODEBASE_OFFLINE=1` (or leave the keys out of the server's environment) for code that must not
  leave the machine. Likely credentials are masked before a file is sent; treat that as a safety net only.
- `codebase-index setup` writes only inside the workspace. It refuses to write through symlinks that leave
  the workspace, and it never edits global client configs. Git hook lines are shell-quoted.

The server's instructions tell the agent that tool results are data, not instructions. That is a hint to
the model, not a security boundary. Treat answers from the index as untrusted data when the repo itself is
untrusted: file contents and
docstrings can contain text that tries to instruct the agent (prompt injection).
