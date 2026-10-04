# FAQ

**Does it send my code anywhere?**
No. Indexing and every tool except one run on your machine with no network calls. The exception is the
optional `summarize_file`, which sends one file to Google or Anthropic, and only if you set an API key.

**Do I need an API key?**
No. Without one, everything works except `summarize_file`. You do not need a key for the subagents either:
they use your editor's own models.

**Is it free?**
Yes. It is MIT licensed, and indexing costs nothing because it uses a parser, not an AI model.

**Does it change my code?**
No. It reads your files and writes only to `.codebase-index/` inside your project (which git-ignores itself)
plus the config files `setup` creates.

**Do I install it in every project?**
No. Install once per computer, then run `codebase-index setup <client>` in each project.

**Which editors and agents work?**
Cursor, Claude Code, VS Code with Copilot and Codex have one-command setup. Anything that can run an MCP
server works through `codebase-index config`. See [other clients](platforms/other-clients.md).

**Which languages?**
Python, JavaScript/JSX and TypeScript/TSX. Adding another is a contained change:
[extending](../developers/extending.md).

**Will it work on a huge repo?**
A 749-file repo indexes in about 3 seconds; later checks take well under a second. Files over 1 MB and
anything git-ignored are skipped.

**How much does it really save?**
It depends on your questions; large files give the biggest wins (often 90%+ on navigation).
Run `codebase-index bench` on your repo. Honest overhead and details: [token savings](../concepts/token-savings.md).

**The assistant still opens whole files. Why?**
It decides what to call. The rule file that `setup` installs steers it; make sure it is in place and
the server is connected. Phrase questions structurally, or say "use the codebase index". Opening a file to
edit most of it is expected.

**Can my team share the setup?**
The generated config contains a path to your Python, so each person should run `setup` themselves. The
instruction blocks (`CLAUDE.md`, `AGENTS.md`, …) are safe to commit. See your editor's guide for details.

**Can I use different models for the subagent?**
Yes: `codebase-index setup cursor --model <id>` or `setup claude-code --model sonnet`.
See [Cursor](platforms/cursor.md#choosing-the-subagent-model) and [Claude Code](platforms/claude-code.md).

**How do I remove it?**
[Install options → uninstall](install.md#upgrade--uninstall).

**It is not working.**
Run `codebase-index doctor`, then see [troubleshooting](troubleshooting.md).
