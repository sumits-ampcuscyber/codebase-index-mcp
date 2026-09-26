## Codebase index (MCP): use it before reading whole files

This repo has a local `codebase-index` MCP server. Its answers cost a few hundred tokens; opening a large
file costs thousands and stays in context. Prefer, in this order:

- `repo_map`: overview of folders and the most-imported files (start here in an unfamiliar repo)
- `search_symbol`: where X is defined (`Class.method`, `Class.`, `two words`, comma-separate several)
- `get_file_summary` / `get_exports`: a file's outline with line ranges and docstrings
- `read_symbol_source`: exact code of one or more symbols; huge symbols come back as a folded skeleton,
  so read only the folded ranges you need with `line_start` / `line_end`
- `find_callers` (`depth=2` for impact) / `find_callees` / `who_imports` / `find_route`
- `summarize_file`: intent of ONE file via a cheap model, only if an API key is configured. After a
  "no API key" error, stop calling it and use `read_symbol_source` on the relevant function instead.

Rules: open a whole file only when you are about to edit most of it. `find_callers` matches by name, so
check the receiver and files before refactoring. Non-code files (Markdown, SQL, YAML, JSON) are not
indexed; read them normally.
