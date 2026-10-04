# Token savings

## Why agents burn tokens on code

Agents pay for **input tokens**, and every tool result stays in the conversation and is **re-sent on every
later turn**. A 3,000-line file read early in a chat is paid for again on each following message. Most of
what an agent reads is not needed: it wanted a signature, a line range or a list of callers.

## What you save

Measured on a 749-file Python + React/TypeScript repo (204k lines), tokens ≈ characters ÷ 4:

| Task | Without | With codebase-index |
|---|---|---|
| Outline of a 5,195-line `.tsx` file | read file: ~64,000 | `get_file_summary`: ~2,700 |
| Code of a 4,028-line component | read file: ~50,000 | skeleton ~2,300, then 1–2 folded ranges |
| Find a symbol | grep output + opening candidates | `search_symbol`: 50–700 |
| Repo orientation | 3–6 turns of ls / Glob / Read | `repo_map`: ~900 |
| Who calls `upgrade` | grep + reading call sites | `find_callers`: ~250 |

Measure your own repo: `codebase-index bench` compares the largest files' full-read cost with their outline
cost.

## Where the savings come from

1. **Facts instead of files.** A signature plus a line range answers most "where / what" questions.
2. **Dense output.** Plain text, one fact per line. The same search as indented JSON was 1,234 tokens; as
   lines, 710 (−42%). Tools use `structured_output=False`, so clients do not receive a duplicate JSON copy.
3. **Folded skeletons.** A huge function returns its shape; the agent reads only the ranges it needs.
4. **Batching.** `search_symbol("a, b, c")` and `read_symbol_source(symbol="a, B.c")` do several lookups
   in one round trip.
5. **Free intent hints.** The first docstring/JSDoc line is stored and shown in outlines and search results,
   which often answers "what is this for?" without reading the body.
6. **Offloading.** `summarize_file` and the `codebase-explorer` subagent run on a cheap model, so the
   expensive main model never sees the raw source.

## The honest overhead

Adding an MCP server is not free:

| Item | Cost | When |
|---|---|---|
| 12 tool definitions | ~1,300–1,500 tokens | once per session, kept in context |
| Server instructions | ~260 tokens | once per session |
| `CLAUDE.md` / `AGENTS.md` / rule block | ~200 tokens (Cursor's rule is longer) | once per session |

That is under 2,000 tokens, i.e. less than one read of a mid-sized file. It pays for itself the first time
the agent uses `get_file_summary` instead of opening a file, and it keeps paying because the savings are
re-sent on every turn. For a very short session on a tiny repo it can be a net cost: that is not what it is for.

## Getting the most out of it

- **Install the rule/instruction file** (`codebase-index setup <client>` does). Models follow explicit
  "use the index first" instructions far more reliably than tool descriptions alone.
- **Use the subagent** (Cursor, Claude Code) for "how does X work" across files. The reading happens on a
  cheap model in a separate context; only a ~300-word answer comes back.
- **Ask structurally.** "Who calls X, what would break?" is a `find_callers depth=2` question (~250 tokens);
  "read the auth module" is not.
- **Prefer ranges.** `read_symbol_source` with `line_start`/`line_end` beats reading a file.
- **Save before asking.** Unsaved buffers are not indexed.
- **Check your context.** Claude Code: `/context`. Cursor: the context indicator in the chat.
- **Open whole files only to edit most of them.**

## What it does not do

It does not shrink your own prompts, the model's output, or the content of files the agent reads anyway
(configs, Markdown, SQL, YAML, JSON are not indexed). It reduces the cost of *navigating* code, which is
usually the largest share of an agent's input.
