"""Exact, cheap lookups over the SQLite index.

Every function returns compact plain text, not pretty-printed JSON: tool output is what the
agent's context pays for, and one line per fact is roughly 40% fewer tokens than indented JSON.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from . import config
from . import indexer

MAX_SOURCE_LINES = 300  # per read_symbol_source call
FOLD_MIN = 6            # skeleton view: statements longer than this are folded
_FUNCS = ("function", "method", "class")


# --------------------------------------------------------------------------- helpers
def normalize_path(file: str) -> str:
    f = file.replace("\\", "/").strip()
    root = config.REPO_ROOT.as_posix().rstrip("/") + "/"
    if f.lower().startswith(root.lower()):
        f = f[len(root):]
    while f.startswith("./"):
        f = f[2:]
    return f.lstrip("/")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def resolve_indexed(con, file: str):
    """Return (rel_path, None) on a unique match, else (None, error_text)."""
    f = normalize_path(file)
    if not f:
        return None, "error: empty file path"
    if con.execute("SELECT 1 FROM files WHERE path=?", (f,)).fetchone():
        return f, None
    cands = [r["path"] for r in con.execute(
        "SELECT path FROM files WHERE path LIKE ? ESCAPE '\\'", ("%" + _esc(f.split("/")[-1]),))
        if r["path"] == f or r["path"].endswith("/" + f)]
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        return None, f"error: '{file}' is ambiguous; use one of:\n" + "\n".join(cands[:15])
    return None, (f"error: '{file}' is not in the index (unsupported file type, ignored by .gitignore, "
                  f"too large, or does not exist). Read it directly instead.")


def safe_disk_path(file: str):
    """Resolve a repo-relative path to a file on disk, refusing anything outside the repo."""
    rel = normalize_path(file)
    p = (config.REPO_ROOT / rel).resolve()
    try:
        p.relative_to(config.REPO_ROOT)
    except ValueError:
        return None, None
    return (rel, p) if p.is_file() else (None, None)


def _qual(parent, name) -> str:
    return f"{parent}.{name}" if parent else name


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."


def _after_name(sig: str | None, name: str, n: int = 160) -> tuple[str, str]:
    """('async ' or '', signature text after the symbol name): def get(self) -> '(self)'."""
    if not sig:
        return "", ""
    i = sig.find(name)
    if i < 0:
        return "", " " + _clip(sig, n)
    return ("async " if "async" in sig[:i] else ""), _clip(sig[i + len(name):], n)


def _level(parent: str | None) -> int:
    return 0 if not parent else parent.count(".") + 1


# --------------------------------------------------------------------------- repo_map
def _pagerank(nodes: list[str], edges: list[tuple[str, str]], iters: int = 30, d: float = 0.85) -> dict:
    n = len(nodes)
    if n == 0:
        return {}
    out: dict[str, list[str]] = {}
    for s, t in edges:
        out.setdefault(s, []).append(t)
    pr = dict.fromkeys(nodes, 1.0 / n)
    for _ in range(iters):
        dangling = sum(pr[v] for v in nodes if v not in out)
        nxt = dict.fromkeys(nodes, (1 - d) / n + d * dangling / n)
        for s, targets in out.items():
            share = d * pr[s] / len(targets)
            for t in targets:
                nxt[t] += share
        pr = nxt
    return pr


def repo_map(path: str = "", limit: int = 30) -> str:
    prefix = normalize_path(path).rstrip("/")
    con = indexer.db()
    if prefix:
        files = con.execute("SELECT path, lang, line_count FROM files WHERE path LIKE ? ESCAPE '\\' "
                            "OR path = ?", (_esc(prefix) + "/%", prefix)).fetchall()
    else:
        files = con.execute("SELECT path, lang, line_count FROM files").fetchall()
    if not files:
        return f"no indexed files under '{path}'" if path else "index is empty (run reindex)"
    paths = [r["path"] for r in files]
    pset = set(paths)
    lines_of = {r["path"]: r["line_count"] or 0 for r in files}
    langs = defaultdict(int)
    for r in files:
        langs[r["lang"]] += 1
    total_lines = sum(lines_of.values())
    out = [f"{config.REPO_ROOT.name}{'/' + prefix if prefix else ''}: {len(files)} files, "
           f"{total_lines:,} lines (" + ", ".join(f"{k} {v}" for k, v in sorted(langs.items(), key=lambda x: -x[1]))
           + ")"]

    # directory overview (two levels below the requested path)
    strip = len(prefix) + 1 if prefix else 0
    dirs = defaultdict(lambda: [0, 0])
    for p in paths:
        parts = p[strip:].split("/")[:-1]
        for depth in (1, 2):
            if len(parts) >= depth:
                key = "/".join(parts[:depth])
                dirs[key][0] += 1
                dirs[key][1] += lines_of[p]
    min_files = max(3, len(files) // 50)
    shown = sorted(k for k, v in dirs.items() if v[0] >= min_files)[:25]
    if shown:
        out.append("dirs:")
        for k in shown:
            files_n, lines_n = dirs[k]
            out.append(f"{'  ' * k.count('/')}  {k}/ {files_n} files, {lines_n:,} lines")

    edges = [(r["src"], r["dst"]) for r in con.execute("SELECT src, dst FROM deps")
             if r["src"] in pset and r["dst"] in pset]
    indeg = defaultdict(int)
    for _, t in edges:
        indeg[t] += 1
    pr = _pagerank(paths, edges)
    ranked = sorted(paths, key=lambda p: (-pr[p], -indeg[p], p))[:max(1, limit)]
    use = {r[0]: r[1] for r in con.execute("SELECT callee, COUNT(DISTINCT file) FROM calls GROUP BY callee")}
    out.append(f"key files (ranked by import graph; <-N = imported by N files):")
    for p in ranked:
        syms = con.execute("SELECT name, kind, exported FROM symbols WHERE file=? AND parent IS NULL "
                           "AND kind != 'variable'", (p,)).fetchall()
        if any(s["exported"] for s in syms):
            syms = [s for s in syms if s["exported"]]
        syms = sorted(syms, key=lambda s: -use.get(s["name"], 0))[:6]
        names = ", ".join(s["name"] + ("()" if s["kind"] in ("function", "method") else "") for s in syms)
        out.append(f"{p} ({lines_of[p]}L, <-{indeg[p]}){': ' + names if names else ''}")
    n_routes = con.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    if n_routes:
        out.append(f"{n_routes} HTTP routes indexed (find_route).")
    return "\n".join(out)


# --------------------------------------------------------------------------- search
def _search_one(con, query: str, kind: str, limit: int) -> str:
    q = query.strip()
    parent, text = None, q
    if "." in q and not q.startswith(".") and " " not in q:
        parent, text = q.rsplit(".", 1)
    words = [w for w in re.split(r"[\s_\-]+", text) if w]
    where, params = [], []
    for w in words:
        where.append("name LIKE ? ESCAPE '\\'")
        params.append("%" + _esc(w) + "%")
    if parent:
        where.append("(parent = ? OR parent LIKE ? ESCAPE '\\')")
        params += [parent, "%." + _esc(parent)]
    if kind:
        where.append("kind = ?")
        params.append(kind)
    cond = " AND ".join(where) or "1=1"
    total = con.execute(f"SELECT COUNT(*) FROM symbols WHERE {cond}", params).fetchone()[0]
    rows = con.execute("SELECT name, kind, parent, file, line_start, line_end, signature, exported, doc "
                       f"FROM symbols WHERE {cond} LIMIT 3000", params).fetchall()
    norm = "".join(words).lower()

    def score(r):
        n = r["name"].lower().replace("_", "")
        return (0 if n == norm else 1 if n.startswith(norm) else 2, _level(r["parent"]) > 1,
                -r["exported"], len(n), r["file"])

    rows.sort(key=score)
    out = [f'"{query}": {total} match{"es" if total != 1 else ""}' + (f" (top {limit})" if total > limit else "")]
    for r in rows[:limit]:
        asyn, rest = _after_name(r["signature"], r["name"], 120)
        line = f"{r['file']}:{r['line_start']}-{r['line_end']} {r['kind']} {asyn}{_qual(r['parent'], r['name'])}{rest}"
        if r["doc"]:
            line += "  # " + _clip(r["doc"], 80)
        out.append(line)
    if total > limit:
        out.append(f"({total - limit} more: refine the query, use Class.method, or pass kind=)")
    return "\n".join(out)


def search_symbol(query: str, kind: str = "", limit: int = 20) -> str:
    queries = [q.strip() for q in query.split(",") if q.strip()]
    if not queries:
        return "error: empty query"
    per = limit if len(queries) == 1 else max(5, limit // len(queries))
    con = indexer.db()
    return "\n\n".join(_search_one(con, q, kind, per) for q in queries)


# --------------------------------------------------------------------------- file-level
def get_file_summary(file: str, depth: int = 1) -> str:
    con = indexer.db()
    rel, err = resolve_indexed(con, file)
    if err:
        return err
    meta = con.execute("SELECT lang, line_count FROM files WHERE path=?", (rel,)).fetchone()
    imports = [r["module"] for r in con.execute(
        "SELECT DISTINCT module FROM imports WHERE file=? ORDER BY module", (rel,))]
    syms = con.execute("SELECT name, kind, parent, line_start, line_end, signature, exported, doc FROM symbols "
                       "WHERE file=? ORDER BY line_start, line_end DESC", (rel,)).fetchall()
    routes = con.execute("SELECT method, path, handler, line FROM routes WHERE file=? ORDER BY line",
                         (rel,)).fetchall()
    out = [f"{rel} ({meta['lang']}, {meta['line_count']} lines, {len(syms)} symbols; * = exported)"]
    if imports:
        shown = imports[:40]
        out.append("imports: " + ", ".join(shown) + (f" (+{len(imports) - 40})" if len(imports) > 40 else ""))
    if routes:
        out.append("routes: " + "; ".join(f"{r['method']} {r['path'] or '(root)'} -> {r['handler']}"
                                          for r in routes[:30])
                   + (f" (+{len(routes) - 30})" if len(routes) > 30 else ""))
    hidden, n = 0, 0
    for s in syms:
        lvl = _level(s["parent"])
        if lvl > depth:
            hidden += 1
            continue
        n += 1
        if n > 300:
            continue
        label = _clip(s["signature"] or s["name"], 140)
        line = f"{'  ' * lvl}L{s['line_start']}-{s['line_end']} {'*' if s['exported'] else ''}{label}"
        if s["doc"]:
            line += "  # " + _clip(s["doc"], 90)
        out.append(line)
    if n > 300:
        out.append(f"(outline truncated: {n} symbols shown up to depth {depth}; use search_symbol)")
    if hidden:
        out.append(f"(+{hidden} deeper nested symbols; pass depth={depth + 1} to show)")
    return "\n".join(out)


def get_exports(file: str) -> str:
    con = indexer.db()
    rel, err = resolve_indexed(con, file)
    if err:
        return err
    rows = con.execute("SELECT name, kind, line_start, line_end, signature, doc FROM symbols "
                       "WHERE file=? AND exported=1 ORDER BY line_start", (rel,)).fetchall()
    out = [f"{rel}: {len(rows)} exports"]
    for r in rows:
        asyn, rest = _after_name(r["signature"], r["name"], 160)
        line = f"L{r['line_start']}-{r['line_end']} {r['kind']} {asyn}{r['name']}{rest}"
        if r["doc"]:
            line += "  # " + _clip(r["doc"], 80)
        out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- call graph
def _caller_rows(con, name: str, receiver: str, limit: int):
    where, params = "callee=?", [name]
    if receiver:
        where += " AND receiver=?"
        params.append(receiver)
    total = con.execute(f"SELECT COUNT(*) FROM calls WHERE {where}", params).fetchone()[0]
    rows = con.execute(f"SELECT file, line, caller, receiver FROM calls WHERE {where} "
                       f"ORDER BY file, line LIMIT ?", params + [limit]).fetchall()
    return total, rows


def find_callers(symbol: str, receiver: str = "", depth: int = 1, limit: int = 30) -> str:
    name = symbol.strip().rsplit(".", 1)[-1]
    if not name:
        return "error: empty symbol"
    con = indexer.db()
    defs = con.execute("SELECT file, parent, name, line_start FROM symbols WHERE name=? AND kind IN "
                       "('function','method','class') ORDER BY file LIMIT 50", (name,)).fetchall()
    total, rows = _caller_rows(con, name, receiver, limit)
    nfiles = len({r["file"] for r in rows})
    out = [f"callers of {name}{' via ' + receiver + '.' if receiver else ''}: {total} call sites"
           + (f" (showing {limit})" if total > limit else f" in {nfiles} files")]
    if defs:
        out.append("defined: " + ", ".join(f"{_qual(d['parent'], d['name'])} {d['file']}:{d['line_start']}"
                                           for d in defs[:5]) + (f" (+{len(defs) - 5})" if len(defs) > 5 else ""))
    if len(defs) > 1:
        out.append(f"! {len(defs)} definitions share this name; calls are matched by NAME. Use the receiver "
                   f"shown after 'via' (or receiver=) and check files before refactoring.")
    by_file = defaultdict(list)
    for r in rows:
        by_file[r["file"]].append(f"L{r['line']} {r['caller']}" + (f" via {r['receiver']}" if r["receiver"] else ""))
    for f, calls in by_file.items():
        out.append(f"{f}: " + ", ".join(calls))

    if depth > 1:
        out.append(f"transitive callers (up to depth {min(depth, 3)}):")
        seen = {name}
        frontier = [r["caller"] for r in rows if r["caller"] and not r["caller"].startswith("<")]
        budget = 60
        for level in range(2, min(depth, 3) + 1):
            nxt = []
            for caller in dict.fromkeys(frontier):
                cname = caller.rsplit(".", 1)[-1]
                if cname in seen or budget <= 0:
                    continue
                seen.add(cname)
                t, rs = _caller_rows(con, cname, "", 8)
                budget -= 1
                where = ", ".join(f"{r['file']}:{r['line']} {r['caller']}" for r in rs) or "(no callers found)"
                out.append(f"{'  ' * (level - 1)}{caller} <- {where}" + (f" (+{t - 8})" if t > 8 else ""))
                nxt += [r["caller"] for r in rs if r["caller"] and not r["caller"].startswith("<")]
            frontier = nxt
    return "\n".join(out)


def find_callees(symbol: str, file: str = "", limit: int = 40) -> str:
    sym = symbol.strip()
    if not sym:
        return "error: empty symbol"
    con = indexer.db()
    where = ("(caller = ? OR caller LIKE ? ESCAPE '\\' OR caller LIKE ? ESCAPE '\\' "
             "OR caller LIKE ? ESCAPE '\\')")
    e = _esc(sym)
    params: list = [sym, "%." + e, e + ".%", "%." + e + ".%"]
    rel = None
    if file:
        rel, err = resolve_indexed(con, file)
        if err:
            return err
        where += " AND file = ?"
        params.append(rel)
    rows = con.execute(f"SELECT callee, receiver, COUNT(*) n, MIN(line) first, file FROM calls WHERE {where} "
                       f"GROUP BY file, callee, receiver ORDER BY file, first", params).fetchall()
    if not rows:
        return f"no calls recorded inside '{sym}'" + (f" in {rel}" if rel else "") + \
            " (check the name with search_symbol; built-ins are not recorded)"
    names = sorted({r["callee"] for r in rows})
    defs = defaultdict(list)
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        for d in con.execute(f"SELECT name, parent, file, line_start FROM symbols WHERE kind IN "
                             f"('function','method','class') AND name IN ({','.join('?' * len(chunk))})", chunk):
            defs[d["name"]].append(d)
    files = sorted({r["file"] for r in rows})
    local, external = [], defaultdict(int)
    for r in rows:
        ds = defs.get(r["callee"])
        call = (f"{r['receiver']}." if r["receiver"] else "") + r["callee"] + "()"
        if not ds:
            external[call if r["receiver"] in (None, "self", "this") else r["callee"]] += r["n"]
            continue
        if len(ds) == 1:
            d0, recv = ds[0], r["receiver"]
            # obj.add() matching the only project method named `add` is a guess unless the receiver
            # is self/this or looks like the owning class.
            guess = (d0["parent"] and recv and recv not in ("self", "this", "cls", "super")
                     and recv.lower().strip("_") not in d0["parent"].lower())
            target = (f"{'maybe ' if guess else ''}{_qual(d0['parent'], d0['name'])} "
                      f"{d0['file']}:{d0['line_start']}")
        else:
            same = [d for d in ds if d["file"] == r["file"]]
            target = (f"{_qual(same[0]['parent'], same[0]['name'])} (same file) L{same[0]['line_start']}"
                      if len(same) == 1 else f"{len(ds)} defs, check with search_symbol")
        prefix = f"{r['file']} " if len(files) > 1 else ""
        local.append(f"{prefix}L{r['first']} {call}{' x' + str(r['n']) if r['n'] > 1 else ''} -> {target}")
    out = [f"{sym} calls {len(local)} project symbols" + (f" (in {len(files)} files: {', '.join(files[:5])})"
                                                         if len(files) > 1 else f" ({files[0]})")]
    out += local[:limit]
    if len(local) > limit:
        out.append(f"(+{len(local) - limit} more)")
    if external:
        ext = sorted(external.items(), key=lambda x: -x[1])[:25]
        out.append("external/unresolved: " + ", ".join(f"{k}{' x' + str(v) if v > 1 else ''}" for k, v in ext)
                   + (f" (+{len(external) - 25})" if len(external) > 25 else ""))
    return "\n".join(out)


def who_imports(file: str, limit: int = 40) -> str:
    con = indexer.db()
    rel, err = resolve_indexed(con, file)
    if err:
        return err
    rows = con.execute("SELECT src, module FROM deps WHERE dst=? ORDER BY src", (rel,)).fetchall()
    uses = con.execute("SELECT dst FROM deps WHERE src=? ORDER BY dst", (rel,)).fetchall()
    out = [f"{rel} is imported by {len(rows)} file{'s' if len(rows) != 1 else ''}"
           + (f" (showing {limit})" if len(rows) > limit else "")]
    out += [f"{r['src']} ({r['module']})" for r in rows[:limit]]
    if not rows:
        out.append("(no static importers: entry point, dynamic/string import, or an alias the resolver "
                   "could not map)")
    if uses:
        out.append(f"it imports {len(uses)} project files: " + ", ".join(r["dst"] for r in uses[:15])
                   + (f" (+{len(uses) - 15})" if len(uses) > 15 else ""))
    return "\n".join(out)


def find_route(query: str = "", method: str = "", limit: int = 50) -> str:
    con = indexer.db()
    q = "%" + _esc(query.strip()) + "%"
    sql = ("SELECT method, path, handler, file, line FROM routes WHERE (path LIKE ? ESCAPE '\\' "
           "OR handler LIKE ? ESCAPE '\\')")
    params: list = [q, q]
    if method:
        sql += " AND (method = ? OR method = '*' OR method LIKE ?)"
        params += [method.upper(), "%" + method.upper() + "%"]
    rows = con.execute(sql + " ORDER BY path, method", params).fetchall()
    if not rows:
        return f"no routes match '{query}'" + (" (no routes are indexed in this repo)"
                                               if not con.execute("SELECT 1 FROM routes LIMIT 1").fetchone() else "")
    out = [f"{len(rows)} route{'s' if len(rows) != 1 else ''}" + (f" (showing {limit})" if len(rows) > limit else "")]
    out += [f"{r['method']} {r['path'] or '(router root)'} -> {r['handler']}  {r['file']}:{r['line']}"
            for r in rows[:limit]]
    out.append("note: paths include the router's own prefix=; prefixes added where a router is mounted "
               "(include_router / app.use) are not applied.")
    return "\n".join(out)


# --------------------------------------------------------------------------- source
_BODY_TYPES = {"block", "statement_block", "class_body", "object", "declaration_list", "enum_body",
               "interface_body", "object_type"}


def _find_body(node, max_nodes: int = 400):
    queue = list(node.named_children)
    i = 0
    while i < len(queue) and i < max_nodes:
        n = queue[i]
        i += 1
        if n.type in _BODY_TYPES and n.end_point[0] > n.start_point[0]:
            if n.type != "object" or (n.parent is not None and n.parent.type == "variable_declarator"):
                return n
        queue.extend(n.named_children)
    return None


def _node_for_range(root, r0: int, r1: int):
    cur = root
    while True:
        nxt = None
        for ch in cur.named_children:
            if ch.start_point[0] <= r0 and ch.end_point[0] >= r1:
                nxt = ch
                break
        if nxt is None:
            return cur
        if nxt.start_point[0] == r0 and nxt.end_point[0] == r1:
            return nxt
        cur = nxt


def _skeleton(rel: str, data: bytes, lines: list[str], a: int, b: int, fold: int):
    lang = config.LANG_BY_EXT.get(PurePosixPath(rel).suffix.lower(), "")
    parser = indexer.get_parser(lang)
    if parser is None:
        return None
    node = _node_for_range(parser.parse(data).root_node, a - 1, b - 1)
    body = _find_body(node)
    if body is None:
        return None
    out: list[str] = []
    last = a - 2

    def emit(r0: int, r1: int) -> None:
        nonlocal last
        for r in range(max(r0, last + 1), min(r1, len(lines) - 1) + 1):
            out.append(lines[r])
        last = max(last, r1)

    emit(a - 1, body.start_point[0])
    for ch in body.named_children:
        s, e = ch.start_point[0], ch.end_point[0]
        if e <= last:
            continue
        if e - s + 1 <= fold:
            emit(s, e)
            continue
        hdr_end = s
        inner = _find_body(ch, 60)
        if inner is not None and 0 <= inner.start_point[0] - s < 3:
            hdr_end = inner.start_point[0]
        emit(s, hdr_end)
        last_line = lines[e].strip() if e < len(lines) else ""
        closing = e if last_line[:1] in ("}", ")", "]") or len(last_line) <= 4 else None
        hid_from, hid_to = max(hdr_end + 1, last + 1), (e - 1 if closing is not None else e)
        if hid_to >= hid_from:
            indent = re.match(r"\s*", lines[hid_from]).group(0)
            out.append(f"{indent}... L{hid_from + 1}-{hid_to + 1} folded ({hid_to - hid_from + 1} lines)")
            last = hid_to
        if closing is not None:
            emit(e, e)
    emit(body.end_point[0], b - 1)
    return out


def read_symbol_source(file: str = "", symbol: str = "", line_start: int = 0, line_end: int = 0,
                       mode: str = "auto") -> str:
    """Exact source for one or more symbols (comma-separated) or a line range, read fresh from disk.

    mode: auto (full source; skeleton when longer than MAX_SOURCE_LINES), full, skeleton."""
    con = indexer.db()
    syms = [s.strip() for s in symbol.split(",") if s.strip()]
    rel_idx = None
    if file:
        rel_idx, err = resolve_indexed(con, file)
        if err and syms:
            return err
    elif not syms:
        return "error: give symbol=... (optionally with file=...) or file= with line_start/line_end"

    targets, notes = [], []  # (rel, a, b, label)
    for s in syms:
        name = s.rsplit(".", 1)[-1]
        parent = s.rsplit(".", 1)[0] if "." in s else None
        sql = "SELECT file, name, parent, line_start, line_end FROM symbols WHERE name=?"
        params: list = [name]
        if rel_idx:
            sql += " AND file=?"
            params.append(rel_idx)
        if parent:
            sql += " AND (parent=? OR parent LIKE ? ESCAPE '\\')"
            params += [parent, "%." + _esc(parent)]
        rows = con.execute(sql + " ORDER BY file, line_start LIMIT 8", params).fetchall()
        if not rows:
            notes.append(f"'{s}' not found{' in ' + rel_idx if rel_idx else ''} (try search_symbol or "
                         f"get_file_summary)")
            continue
        if len({r["file"] for r in rows}) > 1:
            notes.append(f"'{s}' is ambiguous; pass file= one of: " +
                         ", ".join(f"{r['file']}:{r['line_start']}" for r in rows))
            continue
        targets += [(r["file"], r["line_start"], r["line_end"], _qual(r["parent"], r["name"])) for r in rows[:3]]

    if not syms:
        rel, path = safe_disk_path(rel_idx or file)
        if path is None:
            return f"error: cannot read '{file}' (missing or outside the repository)"
        if not line_start:
            return "error: give symbol=... or line_start/line_end"
        end = line_end or line_start + 80
        targets.append((rel, line_start, end, f"lines {line_start}-{end}"))

    out, budget, cache = [], MAX_SOURCE_LINES, {}
    for rel, a, b, label in targets:
        if budget <= 0:
            out.append(f"(line budget used up; read '{label}' in a separate call)")
            continue
        if rel not in cache:
            _, path = safe_disk_path(rel)
            if path is None:
                out.append(f"error: cannot read '{rel}'")
                continue
            data = path.read_bytes()
            cache[rel] = (data, data.decode("utf-8", "replace").splitlines())
        data, lines = cache[rel]
        a, b = max(1, a), min(len(lines), b)
        if b < a:
            out.append(f"error: {rel} has only {len(lines)} lines")
            continue
        n = b - a + 1
        body, how = None, ""
        if mode == "skeleton" or (mode == "auto" and n > budget and syms):
            for fold in (FOLD_MIN, 1):
                body = _skeleton(rel, data, lines, a, b, fold)
                if body is None or len(body) <= budget:
                    break
            if body is not None:
                how = " skeleton (folded blocks: read them with line_start/line_end)"
        if body is None:
            body = lines[a - 1:b]
        if len(body) > budget:
            body = body[:budget] + [f"... truncated at {budget} lines; continue with line_start="
                                    f"{a + budget}" if not how else "... truncated"]
        budget -= len(body)
        out.append(f"== {rel}:{a}-{b} {label} ({n} lines){how}")
        out.append("\n".join(body))
    return "\n".join(notes + out) if (notes or out) else "nothing to read"


# --------------------------------------------------------------------------- stats
def index_stats() -> str:
    con = indexer.db()
    c = lambda t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    langs = ", ".join(f"{r[0]} {r[1]}" for r in con.execute(
        "SELECT lang, COUNT(*) FROM files GROUP BY lang ORDER BY 2 DESC"))
    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    return "\n".join([
        f"repo: {config.REPO_ROOT}",
        f"db: {config.DB_PATH}",
        f"files {c('files')} ({langs}); symbols {c('symbols')}; imports {c('imports')}; "
        f"file deps {c('deps')}; call sites {c('calls')}; routes {c('routes')}",
        f"last sync: {meta.get('last_sync_at', '')}  git: {meta.get('git_head', '')}",
    ])
