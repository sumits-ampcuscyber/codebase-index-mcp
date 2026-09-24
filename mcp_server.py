"""MCP server: structural codebase index tools over stdio.

Stdout is the MCP protocol channel. Logs go to stderr only.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `python mcp_server.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import indexer
import queries
from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="codebase-index",
    instructions=(
        "Structural index of CODEBASE_ROOT. Prefer search_symbol, get_file_summary, "
        "get_exports, find_callers, who_imports, and read_symbol_source before opening "
        "whole files. summarize_file needs an API key."
    ),
)


def _fresh() -> None:
    indexer.ensure_fresh()


@mcp.tool(description="FREE + instant. Find where a function, class, method, interface or type is defined, by (partial) name. Use 'Class.method' to narrow. Optional kind: function, method, class, interface, type, enum, variable.")
def search_symbol(query: str, kind: str = "", limit: int = 20) -> dict:
    _fresh()
    return queries.search_symbol(query, kind=kind, limit=limit)


@mcp.tool(description="FREE + instant. Outline of one file: language, line count, imports, and every class/function/method with signature and line range.")
def get_file_summary(file: str) -> dict:
    _fresh()
    return queries.get_file_summary(file)


@mcp.tool(description="FREE + instant. Public/exported symbols of a file.")
def get_exports(file: str) -> dict:
    _fresh()
    return queries.get_exports(file)


@mcp.tool(description="FREE + instant. Every call site of a function/method name. Matching is by NAME only.")
def find_callers(symbol: str, limit: int = 30) -> dict:
    _fresh()
    return queries.find_callers(symbol, limit=limit)


@mcp.tool(description="FREE + instant. Which files import this file/module.")
def who_imports(file: str, limit: int = 40) -> dict:
    _fresh()
    return queries.who_imports(file, limit=limit)


@mcp.tool(description="FREE. Exact source of ONE function/class/method (symbol) or a line range, read from disk.")
def read_symbol_source(file: str, symbol: str = "", line_start: int = 0, line_end: int = 0) -> dict:
    _fresh()
    return queries.read_symbol_source(file, symbol=symbol, line_start=line_start, line_end=line_end)


@mcp.tool(description="Optional cheap-model summary of one file. Requires GEMINI_API_KEY or ANTHROPIC_API_KEY.")
def summarize_file(file: str, question: str, line_start: int = 0, line_end: int = 0) -> dict:
    _fresh()
    try:
        import cheap_delegate
    except ImportError:
        return {
            "error": (
                "No API key configured for summarize_file (cheap_delegate is not installed). "
                "Use read_symbol_source, or set GEMINI_API_KEY / ANTHROPIC_API_KEY."
            )
        }
    return cheap_delegate.summarize_file(file, question, line_start=line_start, line_end=line_end)


@mcp.tool(description="Force a re-index. Normally unnecessary: the index refreshes itself.")
def reindex(full: bool = False) -> dict:
    return indexer.sync(full=full)


@mcp.tool(description="Counts of indexed files/symbols and the repo root being indexed.")
def index_stats() -> dict:
    _fresh()
    return queries.index_stats()


def main() -> None:
    indexer.start_auto_refresh()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
