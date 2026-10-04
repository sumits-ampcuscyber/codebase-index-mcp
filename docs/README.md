# Documentation

Pick the line that sounds like you.

| I want to... | Read |
|---|---|
| **Just get it working, step by step** (no experience needed) | [Quick start](user-guide/quick-start.md) |
| Set it up for **my editor** | [Cursor](user-guide/platforms/cursor.md) · [Claude Code](user-guide/platforms/claude-code.md) · [VS Code (Copilot)](user-guide/platforms/vscode-copilot.md) · [Codex](user-guide/platforms/codex.md) · [Other clients](user-guide/platforms/other-clients.md) |
| See **what to ask** and how to get the most out of it | [Using it day to day](user-guide/using-it.md) |
| Fix **something that does not work** | [Troubleshooting](user-guide/troubleshooting.md) |
| Get quick answers | [FAQ](user-guide/faq.md) |
| Change settings (API key, subagent model, exclusions, several repos) | [Configuration](user-guide/configuration.md) |
| See other ways to **install** (pip, clone, upgrade, uninstall) | [Install options](user-guide/install.md) |
| Understand **why it saves tokens** and what it costs | [Token savings](concepts/token-savings.md) |
| Understand **how it works inside** (parser, database, freshness, privacy) | [How it works](concepts/how-it-works.md) |
| Look up a **tool or command** | [Tools reference](reference/tools.md) · [Command line reference](reference/cli.md) |
| **Contribute**, add a language or a client | [Contributing](../CONTRIBUTING.md) · [Extending](developers/extending.md) |
| Report a security problem | [Security policy](../SECURITY.md) |

## Map

```text
docs/
├── user-guide/     for people who want to USE it
│   ├── quick-start.md, using-it.md, faq.md, troubleshooting.md
│   ├── configuration.md, install.md
│   └── platforms/  one short guide per editor/agent
├── concepts/       for people who want to UNDERSTAND it
│   ├── token-savings.md, how-it-works.md
├── reference/      for LOOKING THINGS UP
│   ├── tools.md, cli.md
└── developers/     for people who want to CHANGE it
    └── extending.md
```
