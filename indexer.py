"""Parse source files with tree-sitter and store exact structural facts in SQLite.

No LLM is involved here. Cost scales with the number of *changed* files, never with repo size.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import namedtuple
from pathlib import Path, PurePosixPath

import config

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY, lang TEXT, hash TEXT, mtime INTEGER, size INTEGER,
  line_count INTEGER, indexed_at REAL);
CREATE TABLE IF NOT EXISTS symbols(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  parent TEXT, line_start INTEGER, line_end INTEGER, signature TEXT, exported INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file);
CREATE TABLE IF NOT EXISTS imports(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, module TEXT NOT NULL, names TEXT);
CREATE INDEX IF NOT EXISTS idx_imp_file ON imports(file);
CREATE TABLE IF NOT EXISTS calls(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, caller TEXT, callee TEXT NOT NULL, line INTEGER);
CREATE INDEX IF NOT EXISTS idx_call_callee ON calls(callee);
CREATE INDEX IF NOT EXISTS idx_call_file ON calls(file);
CREATE TABLE IF NOT EXISTS summary_cache(
  key TEXT PRIMARY KEY, answer TEXT, model TEXT, created REAL);
"""

_TABLES = ("files", "symbols", "imports", "calls", "summary_cache", "meta")


def log(msg: str) -> None:
    # NEVER print to stdout: stdout is the MCP protocol channel.
    print(f"[codebase-index] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- database
def connect() -> sqlite3.Connection:
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    gi = config.DB_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")  # the index folder ignores itself
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is not None and row["value"] != SCHEMA_VERSION:
        for t in _TABLES:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        row = None
    con.executescript(SCHEMA)
    if row is None:
        con.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (SCHEMA_VERSION,))
        con.commit()
    return con


# --------------------------------------------------------------------------- file discovery
def _git_files(root: Path):
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=60, **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [x for x in out.stdout.decode("utf-8", "replace").split("\0") if x]


def _walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in config.EXCLUDE_DIRS]
        for fn in filenames:
            yield (Path(dirpath) / fn).relative_to(root).as_posix()


def iter_source_files():
    """Yield repo-relative posix paths of supported source files (respects .gitignore)."""
    rels = _git_files(config.REPO_ROOT)
    if rels is None:
        rels = _walk_files(config.REPO_ROOT)
    tool_prefix = (config.TOOL_REL + "/") if config.TOOL_REL else None
    for rel in rels:
        p = PurePosixPath(rel)
        if p.suffix.lower() not in config.LANG_BY_EXT:
            continue
        if any(part in config.EXCLUDE_DIRS for part in p.parts[:-1]):
            continue
        if tool_prefix and rel.startswith(tool_prefix):
            continue
        yield rel


# --------------------------------------------------------------------------- parsing
_PARSERS: dict = {}


def get_parser(lang: str):
    if lang in _PARSERS:
        return _PARSERS[lang]
    parser = None
    try:
        from tree_sitter import Language, Parser

        language = None
        if lang == "python":
            import tree_sitter_python as m
            language = Language(m.language())
        elif lang == "javascript":
            import tree_sitter_javascript as m
            language = Language(m.language())
        elif lang == "typescript":
            import tree_sitter_typescript as m
            language = Language(m.language_typescript())
        elif lang == "tsx":
            import tree_sitter_typescript as m
            language = Language(m.language_tsx())
        if language is not None:
            parser = Parser(language)
    except Exception as e:  # missing grammar package etc.
        log(f"no parser available for {lang}: {e}")
    _PARSERS[lang] = parser
    return parser


Ctx = namedtuple("Ctx", "cls func exported")
_JS_FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}


class Extractor:
    """Walks a tree-sitter AST (iteratively) and collects symbols, imports and calls."""

    def __init__(self, lang: str, src: bytes):
        self.lang = lang
        self.src = src
        self.symbols: list[dict] = []
        self.imports: list[tuple[str, str | None]] = []
        self.calls: list[tuple[str, str, int]] = []
        self.late_exports: set[str] = set()

    # ---- helpers
    def txt(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def name_of(self, node):
        nm = node.child_by_field_name("name")
        return self.txt(nm) if nm is not None else None

    def sig(self, node, body=None) -> str:
        end = body.start_byte if body is not None else node.end_byte
        s = self.src[node.start_byte:end].decode("utf-8", "replace")
        s = " ".join(s.split()).rstrip(" :{").rstrip()
        return s[:300]

    def add(self, node, name, kind, parent, signature, exported, outer=None):
        outer = outer or node
        self.symbols.append({
            "name": name, "kind": kind, "parent": parent,
            "line_start": outer.start_point[0] + 1, "line_end": outer.end_point[0] + 1,
            "signature": signature, "exported": 1 if exported else 0,
        })

    @staticmethod
    def strip_quotes(s: str) -> str:
        return s.strip().strip("'\"`")

    # ---- traversal
    def run(self, root) -> None:
        visit = self.visit_python if self.lang == "python" else self.visit_js
        stack = [(root, Ctx(None, None, False))]
        while stack:
            node, ctx = stack.pop()
            child_ctx = visit(node, ctx)
            for child in reversed(node.children):
                stack.append((child, child_ctx))
        if self.late_exports:
            for s in self.symbols:
                if s["parent"] is None and s["name"] in self.late_exports:
                    s["exported"] = 1

    # ---- Python
    def visit_python(self, n, ctx: Ctx) -> Ctx:
        t = n.type
        if t == "class_definition":
            name = self.name_of(n)
            if name:
                top = ctx.cls is None and ctx.func is None
                outer = n.parent if n.parent is not None and n.parent.type == "decorated_definition" else n
                self.add(n, name, "class", ctx.cls, self.sig(n, n.child_by_field_name("body")),
                         top and not name.startswith("_"), outer)
                qual = name if ctx.cls is None else f"{ctx.cls}.{name}"
                return Ctx(qual, None, False)
        elif t == "function_definition":
            name = self.name_of(n)
            if name and ctx.func is None:  # inner functions are not recorded as symbols
                is_method = ctx.cls is not None
                top = not is_method
                outer = n.parent if n.parent is not None and n.parent.type == "decorated_definition" else n
                self.add(n, name, "method" if is_method else "function", ctx.cls,
                         self.sig(n, n.child_by_field_name("body")),
                         top and not name.startswith("_"), outer)
                qual = f"{ctx.cls}.{name}" if is_method else name
                return Ctx(ctx.cls, qual, False)
        elif t == "call":
            f = n.child_by_field_name("function")
            callee = None
            if f is not None:
                if f.type == "identifier":
                    callee = self.txt(f)
                elif f.type == "attribute":
                    a = f.child_by_field_name("attribute")
                    callee = self.txt(a) if a is not None else None
            if callee:
                self.calls.append((ctx.func or "<module>", callee, n.start_point[0] + 1))
        elif t == "import_statement":
            for c in n.named_children:
                if c.type == "dotted_name":
                    self.imports.append((self.txt(c), None))
                elif c.type == "aliased_import":
                    nm = c.child_by_field_name("name")
                    if nm is not None:
                        self.imports.append((self.txt(nm), None))
        elif t == "import_from_statement":
            mod = n.child_by_field_name("module_name")
            module = self.txt(mod) if mod is not None else ""
            names = []
            for c in n.children_by_field_name("name"):
                if c.type == "aliased_import":
                    nm = c.child_by_field_name("name")
                    names.append(self.txt(nm) if nm is not None else self.txt(c))
                else:
                    names.append(self.txt(c))
            if any(c.type == "wildcard_import" for c in n.children):
                names.append("*")
            if module:
                self.imports.append((module, ", ".join(names)[:300] or None))
        return ctx

    # ---- JavaScript / TypeScript / TSX
    def visit_js(self, n, ctx: Ctx) -> Ctx:
        t = n.type
        top = ctx.cls is None and ctx.func is None
        reset = ctx._replace(exported=False)

        if t == "export_statement":
            src = n.child_by_field_name("source")
            if src is not None:
                self.imports.append((self.strip_quotes(self.txt(src)), "(re-export)"))
            return ctx._replace(exported=True)

        if t == "export_specifier":
            clause = n.parent
            stmt = clause.parent if clause is not None else None
            if stmt is not None and stmt.child_by_field_name("source") is None:
                nm = n.child_by_field_name("name")
                if nm is not None:
                    self.late_exports.add(self.txt(nm))
            return ctx

        outer = n.parent if n.parent is not None and n.parent.type == "export_statement" else n

        if t in ("function_declaration", "generator_function_declaration"):
            name = self.name_of(n)
            if name and ctx.func is None:
                self.add(n, name, "function", None, self.sig(n, n.child_by_field_name("body")),
                         top and ctx.exported, outer)
                return Ctx(None, name, False)
            return reset

        if t in ("class_declaration", "abstract_class_declaration"):
            name = self.name_of(n)
            if name and ctx.func is None:
                self.add(n, name, "class", None, self.sig(n, n.child_by_field_name("body")),
                         top and ctx.exported, outer)
                return Ctx(name, None, False)
            return reset

        if t == "method_definition":
            name = self.name_of(n)
            if name and ctx.cls is not None and ctx.func is None:
                self.add(n, name, "method", ctx.cls, self.sig(n, n.child_by_field_name("body")), False)
                return Ctx(ctx.cls, f"{ctx.cls}.{name}", False)
            return reset

        if t in ("public_field_definition", "field_definition"):
            nm = n.child_by_field_name("name") or n.child_by_field_name("property")
            val = n.child_by_field_name("value")
            if (nm is not None and val is not None and val.type in _JS_FUNC_VALUES
                    and ctx.cls is not None and ctx.func is None):
                name = self.txt(nm)
                self.add(n, name, "method", ctx.cls, self.sig(n, val.child_by_field_name("body")), False)
                return Ctx(ctx.cls, f"{ctx.cls}.{name}", False)
            return reset

        if t in ("interface_declaration", "enum_declaration"):
            name = self.name_of(n)
            if name and top:
                kind = "interface" if t == "interface_declaration" else "enum"
                self.add(n, name, kind, None, self.sig(n, n.child_by_field_name("body")), ctx.exported, outer)
            return reset

        if t == "type_alias_declaration":
            name = self.name_of(n)
            if name and top:
                self.add(n, name, "type", None, self.sig(n)[:200], ctx.exported, outer)
            return reset

        if t == "variable_declarator":
            nm = n.child_by_field_name("name")
            val = n.child_by_field_name("value")
            if nm is not None and nm.type == "identifier" and ctx.func is None and ctx.cls is None:
                name = self.txt(nm)
                decl = n
                while decl.parent is not None and decl.parent.type in (
                        "lexical_declaration", "variable_declaration", "export_statement"):
                    decl = decl.parent
                if val is not None and val.type in _JS_FUNC_VALUES:
                    self.add(n, name, "function", None, self.sig(n, val.child_by_field_name("body")),
                             ctx.exported, decl)
                    return Ctx(None, name, False)
                if ctx.exported:
                    self.add(n, name, "variable", None, self.sig(n)[:160], True, decl)
            return reset

        if t == "call_expression":
            f = n.child_by_field_name("function")
            callee = None
            if f is not None:
                if f.type == "identifier":
                    callee = self.txt(f)
                    if callee == "require":
                        args = n.child_by_field_name("arguments")
                        if args is not None:
                            for a in args.named_children:
                                if a.type == "string":
                                    self.imports.append((self.strip_quotes(self.txt(a)), "(require)"))
                                    break
                elif f.type == "member_expression":
                    p = f.child_by_field_name("property")
                    callee = self.txt(p) if p is not None else None
            if callee:
                self.calls.append((ctx.func or "<module>", callee, n.start_point[0] + 1))
            return ctx

        if t == "new_expression":
            c = n.child_by_field_name("constructor")
            callee = None
            if c is not None:
                if c.type == "identifier":
                    callee = self.txt(c)
                elif c.type == "member_expression":
                    p = c.child_by_field_name("property")
                    callee = self.txt(p) if p is not None else None
            if callee:
                self.calls.append((ctx.func or "<module>", callee, n.start_point[0] + 1))
            return ctx

        if t == "import_statement":
            src = n.child_by_field_name("source")
            if src is not None:
                names = None
                for c in n.named_children:
                    if c.type == "import_clause":
                        names = " ".join(self.txt(c).split())[:300]
                        break
                self.imports.append((self.strip_quotes(self.txt(src)), names))
            return ctx

        return ctx


# --------------------------------------------------------------------------- indexing
def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def index_file(con: sqlite3.Connection, rel: str, data: bytes, digest: str, st: os.stat_result) -> None:
    lang = config.LANG_BY_EXT.get(PurePosixPath(rel).suffix.lower(), "")
    line_count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    ex = None
    if not _is_binary(data):
        parser = get_parser(lang)
        if parser is not None:
            try:
                ex = Extractor(lang, data)
                ex.run(parser.parse(data).root_node)
            except Exception as e:
                log(f"parse error in {rel}: {e}")
                ex = None
    for table in ("symbols", "imports", "calls"):
        con.execute(f"DELETE FROM {table} WHERE file=?", (rel,))
    con.execute(
        "INSERT OR REPLACE INTO files(path, lang, hash, mtime, size, line_count, indexed_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (rel, lang, digest, st.st_mtime_ns, st.st_size, line_count, time.time()),
    )
    if ex is not None:
        con.executemany(
            "INSERT INTO symbols(file,name,kind,parent,line_start,line_end,signature,exported) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [(rel, s["name"], s["kind"], s["parent"], s["line_start"], s["line_end"],
              s["signature"], s["exported"]) for s in ex.symbols],
        )
        con.executemany("INSERT INTO imports(file,module,names) VALUES(?,?,?)",
                        [(rel, m, nm) for m, nm in ex.imports])
        con.executemany("INSERT INTO calls(file,caller,callee,line) VALUES(?,?,?,?)",
                        [(rel, c, e, ln) for c, e, ln in ex.calls])


def sync(full: bool = False) -> dict:
    """Bring the index up to date. Cheap when nothing changed: a stat() per file, and a
    content hash + re-parse only for files whose mtime/size changed."""
    con = connect()
    try:
        known = {r["path"]: r for r in con.execute("SELECT path, hash, mtime, size FROM files")}
        seen: set[str] = set()
        stats = {"scanned": 0, "reindexed": 0, "removed": 0, "skipped_large": 0}
        for rel in iter_source_files():
            abs_path = config.REPO_ROOT / rel
            try:
                st = abs_path.stat()
            except OSError:
                continue
            stats["scanned"] += 1
            if st.st_size > config.MAX_FILE_BYTES:
                stats["skipped_large"] += 1
                continue
            seen.add(rel)
            row = known.get(rel)
            if not full and row and row["mtime"] == st.st_mtime_ns and row["size"] == st.st_size:
                continue
            try:
                data = abs_path.read_bytes()
            except OSError:
                seen.discard(rel)
                continue
            digest = hashlib.sha1(data).hexdigest()
            if not full and row and row["hash"] == digest:
                con.execute("UPDATE files SET mtime=?, size=? WHERE path=?",
                            (st.st_mtime_ns, st.st_size, rel))
                continue
            index_file(con, rel, data, digest, st)
            stats["reindexed"] += 1
        for rel in set(known) - seen:
            for table in ("symbols", "imports", "calls"):
                con.execute(f"DELETE FROM {table} WHERE file=?", (rel,))
            con.execute("DELETE FROM files WHERE path=?", (rel,))
            stats["removed"] += 1
        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('last_sync_at', ?)",
            (str(time.time()),),
        )
        head = _git_head()
        if head:
            con.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('git_head', ?)",
                (head,),
            )
        con.commit()
        return stats
    finally:
        con.close()


def _git_head() -> str:
    """Current branch ref or commit, so a checkout/pull is visible in the stored index."""
    git_dir = config.REPO_ROOT / ".git"
    head = git_dir / "HEAD"
    try:
        text = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if text.startswith("ref:"):
        ref = text.split(":", 1)[1].strip()
        ref_file = git_dir / ref
        try:
            sha = ref_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            sha = ""
        return f"{ref} {sha}".strip()
    return text


_lock = threading.Lock()
_last_sync = 0.0
_watch_started = False
_watch_stop = threading.Event()


def ensure_fresh(min_interval: float = 1.5):
    """Called at the start of every MCP tool call so uncommitted edits are always indexed."""
    global _last_sync
    with _lock:
        now = time.monotonic()
        if now - _last_sync < min_interval:
            return None
        result = sync()
        _last_sync = time.monotonic()
        return result


def start_auto_refresh(interval: float | None = None) -> None:
    """Keep the on-disk index current while the MCP server is running.

    Polls the whole repo (a stat per file, re-parse only what changed) so saves, new
    files, deletes, branch switches, and pulls show up without waiting for a tool call.
    Set CODEBASE_WATCH_INTERVAL=0 to turn this off.
    """
    global _watch_started
    if interval is None:
        interval = float(os.environ.get("CODEBASE_WATCH_INTERVAL", "2"))
    if interval <= 0:
        return
    with _lock:
        if _watch_started:
            return
        _watch_started = True

    def loop() -> None:
        while not _watch_stop.wait(interval):
            try:
                result = ensure_fresh(min_interval=0)
                if result and (result["reindexed"] or result["removed"]):
                    log(
                        f"auto-refresh reindexed={result['reindexed']} "
                        f"removed={result['removed']} scanned={result['scanned']}"
                    )
            except Exception as e:
                log(f"auto-refresh failed: {e}")

    threading.Thread(target=loop, name="codebase-index-watch", daemon=True).start()
    log(f"watching {config.REPO_ROOT} every {interval:g}s -> {config.DB_PATH}")
