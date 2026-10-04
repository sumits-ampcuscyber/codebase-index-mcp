# Using it day to day

Once set up, you do not operate the tool: your AI assistant calls it. Your job is to ask questions in a way
that lets it help.

## What to ask

| You want to know | Ask something like | The assistant uses |
|---|---|---|
| What is in this project? | "Give me an overview of this repo." | `repo_map` |
| Where something lives | "Where is `UserService` defined?" | `search_symbol` |
| What is in a file | "Outline `billing/invoice.py`." | `get_file_summary` |
| A function's code | "Show me `Invoice.total`." | `read_symbol_source` |
| What breaks if I change it | "Who calls `check_token`? What would break?" | `find_callers` (depth 2) |
| What a function depends on | "What does `process_payment` call?" | `find_callees` |
| Who uses a file | "Which files import `lib/api.ts`?" | `who_imports` |
| Which code handles a URL | "What handles `POST /users`?" | `find_route` |
| A flow across many files | "How does login work end to end?" | the `codebase-explorer` subagent (Cursor, Claude Code) |

You can also say it outright: *"use the codebase index"* nudges any assistant to reach for the tools.

## Habits that save the most

1. **Ask for the specific thing**, not the whole file. "Show me `save`" is cheaper than "open `service.py`".
2. **Save your files** before asking. Unsaved editor changes are invisible to the index.
3. **Use the subagent for big questions** ("how does X work") so the raw code never fills your main chat.
4. **Before refactoring**, ask who calls the function. Check the receiver it shows: matching is by name.
5. **Do not paste whole files** into the chat when a line range will do.

## What it will not help with

- Questions about Markdown, SQL, YAML, JSON or config files: those are not indexed, and the assistant
  just reads them normally.
- "Why does this behave oddly at runtime?": the index knows structure, not behaviour. It gets the assistant
  to the right code fast; the assistant still has to read and reason about it.
- Languages other than Python, JavaScript and TypeScript (for now).

## Keeping it fresh

Nothing to do. While your editor runs, a background watcher updates the index within about two seconds of
a file being saved. If you work outside the editor a lot, `codebase-index hooks` refreshes it after every git
commit/checkout. See [configuration](configuration.md#freshness).

## Try it without an assistant

Everything is also a terminal command, handy to see what the assistant sees:

```bash
codebase-index map
codebase-index search "UserService"
codebase-index callers check_token --depth 2
```

All commands: [command line reference](../reference/cli.md).
