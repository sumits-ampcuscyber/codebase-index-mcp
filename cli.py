"""Command-line helper: build/refresh the index and try queries without an IDE.

  python cli.py index            # incremental (fast); run once after install
  python cli.py index --full     # rebuild everything
  python cli.py stats
  python cli.py search MyClass
  python cli.py summary path/to/file.py
  python cli.py callers some_function
  python cli.py importers path/to/file.py
"""
from __future__ import annotations

import argparse
import json
import time

import indexer
import queries


def main() -> None:
    ap = argparse.ArgumentParser(description="codebase-index CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index", help="update the index")
    p.add_argument("--full", action="store_true")
    p.add_argument("--quiet", action="store_true")
    sub.add_parser("stats")
    for name in ("search", "summary", "callers", "importers", "exports"):
        s = sub.add_parser(name)
        s.add_argument("arg")
    a = ap.parse_args()

    if a.cmd == "index":
        t0 = time.time()
        stats = indexer.sync(full=a.full)
        if not a.quiet:
            print(json.dumps({**stats, "seconds": round(time.time() - t0, 2)}, indent=2))
        return
    indexer.ensure_fresh()
    if a.cmd == "stats":
        out = queries.index_stats()
    elif a.cmd == "search":
        out = queries.search_symbol(a.arg)
    elif a.cmd == "summary":
        out = queries.get_file_summary(a.arg)
    elif a.cmd == "callers":
        out = queries.find_callers(a.arg)
    elif a.cmd == "importers":
        out = queries.who_imports(a.arg)
    else:
        out = queries.get_exports(a.arg)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
