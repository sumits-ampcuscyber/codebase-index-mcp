"""`codebase-index bench`: show, on YOUR repo, how many tokens the index saves versus reading files."""
from __future__ import annotations

from . import indexer, queries

TOKEN_CHARS = 4  # rule of thumb: 1 token ~ 4 characters


def tok(text: str) -> int:
    return max(1, len(text) // TOKEN_CHARS)


def run(top: int = 8) -> None:
    indexer.ensure_fresh()
    con = indexer.db()
    rows = con.execute("SELECT path, size, line_count FROM files ORDER BY size DESC LIMIT ?", (top,)).fetchall()
    if not rows:
        print("No indexed files. Check CODEBASE_ROOT and run `codebase-index index`.")
        return
    print(f"{'file':<52} {'lines':>6} {'read file':>10} {'outline':>8} {'saved':>6}")
    tot_full = tot_out = 0
    for r in rows:
        full = r["size"] // TOKEN_CHARS
        out = tok(queries.get_file_summary(r["path"]))
        tot_full += full
        tot_out += out
        path = r["path"] if len(r["path"]) <= 52 else "..." + r["path"][-49:]
        print(f"{path:<52} {r['line_count']:>6} {full:>10,} {out:>8,} {1 - out / max(full, 1):>6.0%}")
    rm = tok(queries.repo_map())
    print(f"\nTotal for these {len(rows)} files: {tot_full:,} -> {tot_out:,} tokens "
          f"({1 - tot_out / max(tot_full, 1):.0%} saved). repo_map (whole-repo orientation): ~{rm:,} tokens.")
    print("Tokens are characters / 4. The server's tool list costs ~1,500 tokens once per session; "
          "one avoided large-file read pays that back.")
