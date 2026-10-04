"""MCP server: structural codebase index tools over stdio.

Stdout is the MCP protocol channel. Logs go to stderr only.
Tools return compact plain text (structured_output=False) so the client does not also receive a
second JSON copy of every answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `python mcp_server.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indexer  # noqa: E402
import queries  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

INSTRUCTIONS = """\
Local structural index of this repository (tree-sitter + SQLite). Answers cost a few hundred tokens
instead of thousands for opening files. Use it BEFORE reading whole files:
- New to the repo / "where do things live?" -> repo_map
- Where is X defined? -> search_symbol (partial names, "Class.method", "two words", several comma-separated)
- What is in a file? -> get_file_summary (outline + docstrings); public API -> get_exports
- Show me the code of X -> read_symbol_source (one or more symbols; huge ones come back as a folded
  skeleton, then read folded ranges by line)
- Who calls X / what does X call / impact -> find_callers (depth=2 for transitive), find_callees
- Who depends on this file -> who_imports; which handler serves an HTTP path -> find_route
- "What does this file do?" for ONE file -> summarize_file (only if an API key is configured; after a
  no-key error, stop calling it)
Open a whole file only when you are about to edit most of it. Results are exact but name-based: verify
call sites before large refactors."""

mcp = MCPServer(name="codebase-index", instructions=INSTRUCTIONS)


def _fresh() -> None:
    indexer.ensure_fresh()


def tool(description: str):
    return mcp.tool(description=description, structured_output=False)


@tool("Overview of the repo (or of path=): size, main folders, and the most-imported files with their key "
      "symbols. Start here in an unfamiliar codebase.")
def repo_map(path: str = "", limit: int = 30) -> str:
    _fresh()
    return queries.repo_map(path, limit=limit)


@tool("Find where functions/classes/methods/types are defined by (partial) name. 'Class.method' narrows by "
      "parent, 'Class.' lists members, 'accept evidence' matches acceptEvidence/accept_evidence, commas run "
      "several searches. kind: function|method|class|interface|type|enum|variable.")
def search_symbol(query: str, kind: str = "", limit: int = 20) -> str:
    _fresh()
    return queries.search_symbol(query, kind=kind, limit=limit)


@tool("Outline of one file: imports, HTTP routes, every class/function/method with line range, signature "
      "and first docstring line. depth=2 also shows functions nested inside functions/methods.")
def get_file_summary(file: str, depth: int = 1) -> str:
    _fresh()
    return queries.get_file_summary(file, depth=depth)


@tool("Public/exported symbols of a file with signatures.")
def get_exports(file: str) -> str:
    _fresh()
    return queries.get_exports(file)


@tool("Exact source of one or more symbols (comma-separated, 'Class.method' ok; file optional when the name "
      "is unique) or of file + line_start/line_end. mode=auto returns a folded skeleton for very large "
      "symbols; mode=full|skeleton forces one.")
def read_symbol_source(file: str = "", symbol: str = "", line_start: int = 0, line_end: int = 0,
                       mode: str = "auto") -> str:
    _fresh()
    return queries.read_symbol_source(file, symbol=symbol, line_start=line_start, line_end=line_end, mode=mode)


@tool("Call sites of a function/method, grouped by file, with the enclosing caller and receiver. Matching is "
      "by name: filter with receiver= (e.g. 'repo' for self.repo.save). depth=2..3 adds callers-of-callers "
      "(impact analysis).")
def find_callers(symbol: str, receiver: str = "", depth: int = 1, limit: int = 30) -> str:
    _fresh()
    return queries.find_callers(symbol, receiver=receiver, depth=depth, limit=limit)


@tool("What a function/method/class calls (including its nested functions), resolved to project definitions "
      "where possible; library calls are summarised on one line.")
def find_callees(symbol: str, file: str = "", limit: int = 40) -> str:
    _fresh()
    return queries.find_callees(symbol, file=file, limit=limit)


@tool("Which project files import this file (resolved imports: relative paths, tsconfig aliases, Python "
      "packages), plus the project files it imports.")
def who_imports(file: str, limit: int = 40) -> str:
    _fresh()
    return queries.who_imports(file, limit=limit)


@tool("HTTP routes (FastAPI/Flask decorators, Express router.get(...)) matching a path or handler "
      "substring; optional method=GET|POST|...")
def find_route(query: str = "", method: str = "", limit: int = 50) -> str:
    _fresh()
    return queries.find_route(query, method=method, limit=limit)


@tool("Costs a small API call. Cheap-model answer to a question about ONE file or line range (cached). "
      "Needs GEMINI_API_KEY/GOOGLE_API_KEY or ANTHROPIC_API_KEY; after a no-key error do not retry.")
def summarize_file(file: str, question: str, line_start: int = 0, line_end: int = 0) -> str:
    _fresh()
    import cheap_delegate
    return cheap_delegate.summarize_file(file, question, line_start=line_start, line_end=line_end)


@tool("Force a re-index (full=true rebuilds everything). Normally unnecessary: the index refreshes itself.")
def reindex(full: bool = False) -> str:
    s = indexer.refresh(full=full)
    return (f"scanned {s['scanned']}, reindexed {s['reindexed']}, removed {s['removed']}, "
            f"skipped (too large) {s['skipped_large']}")


@tool("Index health: repo root, counts, last sync time and git HEAD.")
def index_stats() -> str:
    _fresh()
    return queries.index_stats()


def main() -> None:
    indexer.start_auto_refresh()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
