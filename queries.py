"""Exact, cheap lookups over the SQLite index. Every function returns small JSON-able dicts."""
from __future__ import annotations

import re
from contextlib import closing
from pathlib import PurePosixPath

import config
import indexer

MAX_SOURCE_LINES = 300


# --------------------------------------------------------------------------- path helpers
def normalize_path(file: str) -> str:
    f = file.replace("\\", "/").strip()
    root = config.REPO_ROOT.as_posix().rstrip("/") + "/"
    if f.lower().startswith(root.lower()):
        f = f[len(root):]
    while f.startswith("./"):
        f = f[2:]
    return f.lstrip("/")


def resolve_indexed(con, file: str):
    """Return (rel_path, None) on a unique match, else (None, error_dict)."""
    f = normalize_path(file)
    if con.execute("SELECT 1 FROM files WHERE path=?", (f,)).fetchone():
        return f, None
    cands = [r["path"] for r in con.execute("SELECT path FROM files WHERE path LIKE ?", ("%" + f.split("/")[-1],))
             if r["path"] == f or r["path"].endswith("/" + f)]
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        return None, {"error": f"'{file}' is ambiguous; use one of these paths", "candidates": cands[:15]}
    return None, {"error": f"'{file}' is not in the index (unsupported file type, ignored by .gitignore, "
                           f"or does not exist). Read it directly instead."}


def safe_disk_path(file: str):
    """Resolve a repo-relative path to a file on disk, refusing anything outside the repo."""
    rel = normalize_path(file)
    p = (config.REPO_ROOT / rel).resolve()
    try:
        p.relative_to(config.REPO_ROOT)
    except ValueError:
        return None, None
    return (rel, p) if p.is_file() else (None, None)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _loc(r) -> str:
    return f"{r['file']}:{r['line_start']}-{r['line_end']}"


# --------------------------------------------------------------------------- tools
def search_symbol(query: str, kind: str = "", limit: int = 20) -> dict:
    q = query.strip()
    parent = None
    if "." in q and not q.startswith("."):
        parent, q = q.rsplit(".", 1)
    with closing(indexer.connect()) as con:
        sql = ("SELECT name, kind, parent, file, line_start, line_end, signature, exported "
               "FROM symbols WHERE name LIKE ? ESCAPE '\\'")
        params: list = ["%" + _esc(q) + "%"]
        if parent:
            sql += " AND (parent = ? OR parent LIKE ? ESCAPE '\\')"
            params += [parent, "%." + _esc(parent)]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        rows = con.execute(sql + " LIMIT 500", params).fetchall()

    ql = q.lower()

    def score(r):
        n = r["name"].lower()
        return (0 if n == ql else 1 if n.startswith(ql) else 2, -r["exported"], len(n), r["file"])

    rows.sort(key=score)
    out = [{
        "symbol": (f"{r['parent']}.{r['name']}" if r["parent"] else r["name"]),
        "kind": r["kind"], "at": _loc(r), "signature": r["signature"],
    } for r in rows[:limit]]
    res = {"query": query, "matches": len(rows), "results": out}
    if len(rows) > limit:
        res["note"] = f"{len(rows) - limit} more matches; refine the query or pass kind=."
    return res


def get_file_summary(file: str) -> dict:
    with closing(indexer.connect()) as con:
        rel, err = resolve_indexed(con, file)
        if err:
            return err
        meta = con.execute("SELECT lang, line_count FROM files WHERE path=?", (rel,)).fetchone()
        imports = [r["module"] for r in con.execute(
            "SELECT DISTINCT module FROM imports WHERE file=? ORDER BY module", (rel,))]
        syms = con.execute(
            "SELECT name, kind, parent, line_start, line_end, signature, exported FROM symbols "
            "WHERE file=? ORDER BY line_start", (rel,)).fetchall()
    outline = []
    for s in syms[:250]:
        label = s["signature"] or s["name"]
        if len(label) > 150:
            label = label[:147] + "..."
        indent = "    " if s["parent"] else ""
        outline.append(f"{indent}L{s['line_start']}-{s['line_end']} {label}{'  [exported]' if s['exported'] else ''}")
    res = {"file": rel, "language": meta["lang"], "lines": meta["line_count"],
           "imports": imports, "outline": outline}
    if len(syms) > 250:
        res["note"] = f"outline truncated ({len(syms)} symbols total)"
    return res


def get_exports(file: str) -> dict:
    with closing(indexer.connect()) as con:
        rel, err = resolve_indexed(con, file)
        if err:
            return err
        rows = con.execute(
            "SELECT name, kind, line_start, line_end, signature FROM symbols "
            "WHERE file=? AND exported=1 ORDER BY line_start", (rel,)).fetchall()
    return {"file": rel, "exports": [
        {"name": r["name"], "kind": r["kind"], "lines": f"{r['line_start']}-{r['line_end']}",
         "signature": r["signature"]} for r in rows]}


def find_callers(symbol: str, limit: int = 30) -> dict:
    name = symbol.strip().rsplit(".", 1)[-1]
    with closing(indexer.connect()) as con:
        total = con.execute("SELECT COUNT(*) c FROM calls WHERE callee=?", (name,)).fetchone()["c"]
        rows = con.execute(
            "SELECT file, line, caller FROM calls WHERE callee=? ORDER BY file, line LIMIT ?",
            (name, limit)).fetchall()
        defs = con.execute(
            "SELECT file, parent, name, line_start, line_end FROM symbols "
            "WHERE name=? AND kind IN ('function','method','class') LIMIT 10", (name,)).fetchall()
    res = {
        "symbol": name,
        "defined_in": [f"{(d['parent'] + '.') if d['parent'] else ''}{d['name']} @ {d['file']}:{d['line_start']}"
                       for d in defs],
        "total_call_sites": total,
        "callers": [f"{r['file']}:{r['line']}  in {r['caller']}" for r in rows],
    }
    if len(defs) > 1:
        res["warning"] = (f"{len(defs)} different symbols are named '{name}'. Call sites are matched by NAME only, "
                          "so some listed callers may call a different one. Verify before refactoring.")
    if total > limit:
        res["note"] = f"showing {limit} of {total}"
    return res


def _module_matches(module: str, rel: str, names: str | None) -> bool:
    parts = PurePosixPath(rel).with_suffix("").as_posix().split("/")
    stem = parts[-1]
    if stem in ("__init__", "index"):
        parts = parts[:-1]
        stem = parts[-1] if parts else ""
    if not parts:
        return False
    m = module.strip()
    if "/" in m:  # JS/TS style path
        m = re.sub(r"\.(js|jsx|ts|tsx|mjs|cjs)$", "", m)
        mp = [x for x in m.split("/") if x not in (".", "..", "")]
        if mp and mp[0] in ("@", "~", "#"):
            mp = mp[1:]
    else:  # Python dotted / relative path, or bare JS specifier
        mp = [x for x in m.split(".") if x]
    if mp and parts[-len(mp):] == mp:
        return True
    # "from pkg import stem"  ->  module is the parent package, stem is in the imported names
    if names and stem:
        imported = {n.strip() for n in names.split(",")}
        parent_parts = parts[:-1]
        if stem in imported and mp and parent_parts[-len(mp):] == mp:
            return True
    return False


def who_imports(file: str, limit: int = 40) -> dict:
    with closing(indexer.connect()) as con:
        rel, err = resolve_indexed(con, file)
        if err:
            return err
        stem = PurePosixPath(rel).stem
        if stem in ("__init__", "index"):
            stem = PurePosixPath(rel).parent.name
        rows = con.execute(
            "SELECT DISTINCT file, module, names FROM imports WHERE module LIKE ? ESCAPE '\\' "
            "OR names LIKE ? ESCAPE '\\'", ("%" + _esc(stem) + "%", "%" + _esc(stem) + "%")).fetchall()
    by_file: dict[str, set] = {}
    for r in rows:
        if r["file"] != rel and _module_matches(r["module"], rel, r["names"]):
            by_file.setdefault(r["file"], set()).add(r["module"])
    hits = sorted(by_file)
    res = {"file": rel,
           "importers": [f"{f}  (via {', '.join(sorted(by_file[f]))})" for f in hits[:limit]],
           "total": len(hits),
           "note": "Matched by module-path suffix; aliases, re-exports and dynamic imports can be missed."}
    if len(hits) > limit:
        res["note"] += f" Showing {limit} of {len(hits)}."
    return res


def read_symbol_source(file: str, symbol: str = "", line_start: int = 0, line_end: int = 0) -> dict:
    """Return exact source for one symbol or a line range, read fresh from disk."""
    with closing(indexer.connect()) as con:
        rel_idx, _ = resolve_indexed(con, file)
        ranges = []
        if symbol:
            if rel_idx is None:
                return {"error": f"'{file}' is not indexed, so symbol lookup is unavailable. Pass line_start/line_end."}
            name = symbol.strip().rsplit(".", 1)[-1]
            parent = symbol.strip().rsplit(".", 1)[0] if "." in symbol.strip() else None
            sql = "SELECT name, parent, line_start, line_end FROM symbols WHERE file=? AND name=?"
            params = [rel_idx, name]
            if parent:
                sql += " AND (parent=? OR parent LIKE ?)"
                params += [parent, "%." + parent]
            rows = con.execute(sql + " ORDER BY line_start LIMIT 5", params).fetchall()
            if not rows:
                return {"error": f"symbol '{symbol}' not found in {rel_idx}. Try get_file_summary first."}
            ranges = [(r["line_start"], r["line_end"], f"{r['parent'] + '.' if r['parent'] else ''}{r['name']}")
                      for r in rows]
    rel, path = safe_disk_path(rel_idx or file)
    if path is None:
        return {"error": f"cannot read '{file}' (missing or outside the repository)"}
    if not ranges:
        if not line_start:
            return {"error": "give either symbol=... or line_start/line_end"}
        ranges = [(line_start, line_end or line_start + 80, f"lines {line_start}-{line_end or line_start + 80}")]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    chunks, budget = [], MAX_SOURCE_LINES
    for a, b, label in ranges:
        a = max(1, a)
        b = min(len(lines), b)
        take = lines[a - 1:b]
        truncated = len(take) > budget
        take = take[:budget]
        budget -= len(take)
        chunks.append({"what": label, "lines": f"{a}-{a + len(take) - 1}", "source": "\n".join(take),
                       **({"truncated": True} if truncated else {})})
        if budget <= 0:
            break
    return {"file": rel, "chunks": chunks}


def index_stats() -> dict:
    with closing(indexer.connect()) as con:
        c = lambda t: con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        langs = {r["lang"]: r["n"] for r in con.execute("SELECT lang, COUNT(*) n FROM files GROUP BY lang")}
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
        return {"repo_root": str(config.REPO_ROOT), "db": str(config.DB_PATH), "files": c("files"),
                "symbols": c("symbols"), "imports": c("imports"), "call_sites": c("calls"),
                "languages": langs, "last_sync_at": meta.get("last_sync_at", ""),
                "git_head": meta.get("git_head", "")}
