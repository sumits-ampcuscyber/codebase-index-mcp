"""Command-line helper: build/refresh the index and try every query without an IDE.

  python cli.py index [--full]        # incremental (fast); run once after install
  python cli.py stats
  python cli.py map [path]
  python cli.py search "MyClass, other thing"
  python cli.py summary path/to/file.py [--depth 2]
  python cli.py exports path/to/file.py
  python cli.py source SymbolName [--file path] [--mode auto|full|skeleton]
  python cli.py callers some_function [--depth 2]
  python cli.py callees SomeClass.method
  python cli.py importers path/to/file.py
  python cli.py routes /users [--method GET]
  python cli.py ask path/to/file.py "what does it do?"   # cheap model, needs an API key
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import indexer
import queries


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="codebase-index CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index", help="update the index")
    p.add_argument("--full", action="store_true")
    p.add_argument("--quiet", action="store_true")
    sub.add_parser("stats")
    p = sub.add_parser("map")
    p.add_argument("path", nargs="?", default="")
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("search")
    p.add_argument("arg")
    p.add_argument("--kind", default="")
    p = sub.add_parser("summary")
    p.add_argument("arg")
    p.add_argument("--depth", type=int, default=1)
    for name in ("exports", "importers", "callees"):
        sub.add_parser(name).add_argument("arg")
    p = sub.add_parser("callers")
    p.add_argument("arg")
    p.add_argument("--receiver", default="")
    p.add_argument("--depth", type=int, default=1)
    p = sub.add_parser("source")
    p.add_argument("arg", help="symbol name(s), comma-separated")
    p.add_argument("--file", default="")
    p.add_argument("--mode", default="auto")
    p = sub.add_parser("routes")
    p.add_argument("arg", nargs="?", default="")
    p.add_argument("--method", default="")
    p = sub.add_parser("ask")
    p.add_argument("file")
    p.add_argument("question")
    a = ap.parse_args()

    if a.cmd == "index":
        t0 = time.time()
        stats = indexer.refresh(full=a.full)
        if not a.quiet:
            print(json.dumps({**stats, "seconds": round(time.time() - t0, 2)}, indent=2))
        return
    indexer.ensure_fresh()
    if a.cmd == "stats":
        out = queries.index_stats()
    elif a.cmd == "map":
        out = queries.repo_map(a.path, limit=a.limit)
    elif a.cmd == "search":
        out = queries.search_symbol(a.arg, kind=a.kind)
    elif a.cmd == "summary":
        out = queries.get_file_summary(a.arg, depth=a.depth)
    elif a.cmd == "exports":
        out = queries.get_exports(a.arg)
    elif a.cmd == "callers":
        out = queries.find_callers(a.arg, receiver=a.receiver, depth=a.depth)
    elif a.cmd == "callees":
        out = queries.find_callees(a.arg)
    elif a.cmd == "importers":
        out = queries.who_imports(a.arg)
    elif a.cmd == "source":
        out = queries.read_symbol_source(a.file, symbol=a.arg, mode=a.mode)
    elif a.cmd == "routes":
        out = queries.find_route(a.arg, method=a.method)
    else:
        import cheap_delegate
        out = cheap_delegate.summarize_file(a.file, a.question)
    print(out)


if __name__ == "__main__":
    main()
