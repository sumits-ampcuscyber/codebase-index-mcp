## Codebase index (MCP): use it before reading files

A local `codebase-index` MCP server answers structural questions in a few hundred tokens; opening a
large file costs thousands and stays in context. Prefer it over Read/Grep on source files:

- `repo_map`: folders + most-imported files (start here in an unfamiliar repo)
- `search_symbol`: where is X defined (`Class.method`, `Class.`, `two words`, comma-separate several)
- `get_file_summary` / `get_exports`: a file's outline with line ranges
- `read_symbol_source`: exact code of symbols; huge ones come back folded, then read only the folded
  ranges with `line_start` / `line_end`
- `find_callers` (`depth=2` for impact) / `find_callees` / `who_imports` / `find_route`
- `summarize_file`: only if an API key is configured; after a "no API key" error, stop calling it

Open a whole file only when about to edit most of it. `find_callers` matches by name: check the
receiver before refactoring. Markdown/SQL/YAML/JSON are not indexed; read them normally. Save files
before asking: unsaved editor buffers are not indexed.
