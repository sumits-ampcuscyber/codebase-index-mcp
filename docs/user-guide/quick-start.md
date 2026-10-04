# Quick start

This takes about five minutes. You do not need to know how it works.

**What you are doing:** installing a small helper once on your computer, then switching it on for each
project you want your AI coding assistant to understand cheaply.

## Before you begin

You need two things. Check them by typing these in a terminal (on Windows: PowerShell):

```bash
python --version      # must say 3.10 or higher
git --version         # any version
```

Missing one? Install [Python](https://www.python.org/downloads/) (on Windows, tick "Add Python to PATH") and
[git](https://git-scm.com/downloads), then open a **new** terminal.

## Step 1. Install the tool (once per computer)

```bash
python -m pip install --user pipx
python -m pipx ensurepath
```

Close the terminal and open a new one, then:

```bash
pipx install git+https://github.com/sumits-ampcuscyber/codebase-index-mcp.git
```

Check it worked:

```bash
codebase-index --version
```

You should see `codebase-index 0.2.0` (or newer). If you see "command not found", close and reopen the
terminal; if it still fails, see [troubleshooting](troubleshooting.md#install-problems).

## Step 2. Switch it on for your project (once per project)

Go to the folder of the project you open in your editor, then run the line for your editor:

```bash
cd path/to/your-project

codebase-index setup cursor         # Cursor
codebase-index setup claude-code    # Claude Code
codebase-index setup vscode         # VS Code with GitHub Copilot
codebase-index setup codex          # OpenAI Codex
codebase-index setup all            # all of the above
```

It prints each file it wrote. It never deletes your existing settings, and running it twice is harmless.
Use `--dry-run` first if you want to see what it would do without changing anything.

## Step 3. Check everything is connected

```bash
codebase-index doctor
```

Every line should start with `[ok]`. A `[warn]` is usually fine (for example "no index yet" before first use).
A `[FAIL]` tells you what to fix.

## Step 4. Restart your editor and try it

Restart the editor (or reload the window) so it picks up the new server, then follow the last step for yours:

| Editor | Confirm it is connected |
|---|---|
| Cursor | Settings → MCP: the server has a green dot and 12 tools |
| Claude Code | Type `/mcp` in a session in your project; approve the server if asked |
| VS Code | Command Palette → "MCP: List Servers" → start it; use Copilot Chat in **Agent** mode |
| Codex | Run the `codex mcp add ...` command that `setup codex` printed, then restart Codex |

Now ask your assistant:

> *"Use the codebase index to find where `<something in your project>` is defined and show me its code."*

When it works you will see tool calls named `search_symbol`, `get_file_summary` or `read_symbol_source`
instead of the assistant opening whole files.

## Step 5 (optional). See what you are saving

```bash
codebase-index bench
```

It shows, for your biggest files, the tokens a full read would cost versus the index's answer.

## That is it

- A new project later? Repeat **Step 2** only. Step 1 is once per computer.
- Having trouble? [Troubleshooting](troubleshooting.md) and the [FAQ](faq.md).
- Want to get more out of it? [Using it day to day](using-it.md).
- Your editor in detail: [Cursor](platforms/cursor.md) · [Claude Code](platforms/claude-code.md) ·
  [VS Code](platforms/vscode-copilot.md) · [Codex](platforms/codex.md) · [others](platforms/other-clients.md).
