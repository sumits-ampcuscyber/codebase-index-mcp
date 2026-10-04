"""codebase-index: build the index, query it from a terminal, and wire it into your agent.

  codebase-index setup cursor|claude-code|vscode|codex|all   configure an agent client for this repo
  codebase-index config                                      print generic mcpServers JSON
  codebase-index doctor                                      diagnose install / repo / client wiring
  codebase-index bench                                       tokens saved vs reading files, on your repo
  codebase-index hooks [--uninstall]                         git hooks that refresh the index

  codebase-index index [--full]        build / refresh (incremental, fast)
  codebase-index stats
  codebase-index map [path]
  codebase-index search "MyClass, other thing"
  codebase-index summary path/to/file.py [--depth 2]
  codebase-index exports path/to/file.py
  codebase-index source SymbolName [--file path] [--mode auto|full|skeleton]
  codebase-index callers some_function [--receiver x] [--depth 2]
  codebase-index callees SomeClass.method
  codebase-index importers path/to/file.py
  codebase-index routes /users [--method GET]
  codebase-index ask path/to/file.py "what does it do?"   (cheap model, needs an API key)

The repo is the git root of the current directory, or $CODEBASE_ROOT.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="codebase-index", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"codebase-index {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("index", help="build or refresh the index")
    p.add_argument("--full", action="store_true", help="rebuild from scratch")
    p.add_argument("--quiet", action="store_true")
    sub.add_parser("stats", help="index health")
    p = sub.add_parser("map", help="repo overview")
    p.add_argument("path", nargs="?", default="")
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("search", help="find symbol definitions")
    p.add_argument("arg")
    p.add_argument("--kind", default="")
    p = sub.add_parser("summary", help="outline of a file")
    p.add_argument("arg")
    p.add_argument("--depth", type=int, default=1)
    for name, h in (("exports", "public API of a file"), ("importers", "who imports a file"),
                    ("callees", "what a symbol calls")):
        sub.add_parser(name, help=h).add_argument("arg")
    p = sub.add_parser("callers", help="call sites of a symbol")
    p.add_argument("arg")
    p.add_argument("--receiver", default="")
    p.add_argument("--depth", type=int, default=1)
    p = sub.add_parser("source", help="exact code of symbols")
    p.add_argument("arg", help="symbol name(s), comma-separated")
    p.add_argument("--file", default="")
    p.add_argument("--mode", default="auto")
    p = sub.add_parser("routes", help="HTTP routes")
    p.add_argument("arg", nargs="?", default="")
    p.add_argument("--method", default="")
    p = sub.add_parser("ask", help="cheap-model answer about one file (needs an API key)")
    p.add_argument("file")
    p.add_argument("question")

    p = sub.add_parser("setup", help="configure an agent client for this repo")
    p.add_argument("client", choices=("cursor", "claude-code", "vscode", "codex", "all"))
    p.add_argument("--workspace", default=None, help="folder to write config into (default: the indexed repo)")
    p.add_argument("--name", default=None, help="MCP server name (default: codebase-index-<repo>)")
    p.add_argument("--model", default=None,
                   help="subagent model: Cursor model id (default grok-4.7) or Claude Code alias (default haiku)")
    p.add_argument("--no-subagent", action="store_true", help="do not install the codebase-explorer subagent")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p = sub.add_parser("config", help="print generic mcpServers JSON for any other MCP client")
    p.add_argument("--name", default=None)
    sub.add_parser("doctor", help="diagnose install, repo and client wiring")
    p = sub.add_parser("bench", help="tokens saved vs reading whole files, on this repo")
    p.add_argument("--top", type=int, default=8, help="how many of the largest files to compare")
    p = sub.add_parser("hooks", help="install git hooks that refresh the index")
    p.add_argument("--uninstall", action="store_true")
    sub.add_parser("refresh-detached")  # used by the git hooks
    return ap


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args(argv)

    # Commands that do not need the index loaded: import lazily so `setup` / `doctor` stay fast.
    if a.cmd == "setup":
        from . import clients
        return clients.run_setup(a)
    if a.cmd == "config":
        from . import clients
        return clients.print_config(a)
    if a.cmd == "doctor":
        from . import doctor
        sys.exit(doctor.run())
    if a.cmd == "hooks":
        from . import hooks
        return hooks.install(uninstall=a.uninstall)
    if a.cmd == "refresh-detached":
        from . import hooks
        return hooks.refresh_detached()

    from . import indexer, queries
    if a.cmd == "index":
        t0 = time.time()
        stats = indexer.refresh(full=a.full)
        if not a.quiet:
            print(json.dumps({**stats, "seconds": round(time.time() - t0, 2)}, indent=2))
        return
    if a.cmd == "bench":
        from . import bench
        return bench.run(a.top)
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
        from . import cheap_delegate
        out = cheap_delegate.summarize_file(a.file, a.question)
    print(out)


if __name__ == "__main__":
    main()
