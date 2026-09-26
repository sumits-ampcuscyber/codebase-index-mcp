"""Parse source files with tree-sitter and store exact structural facts in SQLite.

No LLM is involved here. Cost scales with the number of *changed* files, never with repo size.
"""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import posixpath
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import namedtuple
from pathlib import Path, PurePosixPath

import config

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY, lang TEXT, hash TEXT, mtime INTEGER, size INTEGER,
  line_count INTEGER, indexed_at REAL);
CREATE TABLE IF NOT EXISTS symbols(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  parent TEXT, line_start INTEGER, line_end INTEGER, signature TEXT, exported INTEGER DEFAULT 0,
  doc TEXT);
CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file);
CREATE INDEX IF NOT EXISTS idx_sym_parent ON symbols(parent);
CREATE TABLE IF NOT EXISTS imports(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, module TEXT NOT NULL, names TEXT, line INTEGER);
CREATE INDEX IF NOT EXISTS idx_imp_file ON imports(file);
CREATE TABLE IF NOT EXISTS deps(src TEXT NOT NULL, dst TEXT NOT NULL, module TEXT,
  PRIMARY KEY(src, dst));
CREATE INDEX IF NOT EXISTS idx_deps_dst ON deps(dst);
CREATE TABLE IF NOT EXISTS calls(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, caller TEXT, callee TEXT NOT NULL, receiver TEXT,
  line INTEGER);
CREATE INDEX IF NOT EXISTS idx_call_callee ON calls(callee);
CREATE INDEX IF NOT EXISTS idx_call_file ON calls(file);
CREATE INDEX IF NOT EXISTS idx_call_caller ON calls(caller);
CREATE TABLE IF NOT EXISTS routes(
  id INTEGER PRIMARY KEY, file TEXT NOT NULL, method TEXT, path TEXT, handler TEXT, line INTEGER);
CREATE INDEX IF NOT EXISTS idx_routes_file ON routes(file);
CREATE TABLE IF NOT EXISTS summary_cache(
  key TEXT PRIMARY KEY, answer TEXT, model TEXT, created REAL);
"""

_TABLES = ("files", "symbols", "imports", "deps", "calls", "routes", "summary_cache", "meta")
_PER_FILE_TABLES = ("symbols", "imports", "calls", "routes")


def log(msg: str) -> None:
    # NEVER print to stdout: stdout is the MCP protocol channel.
    print(f"[codebase-index] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- database
_schema_ready: set[str] = set()
_schema_lock = threading.Lock()
_local = threading.local()


def _init_schema(con: sqlite3.Connection) -> None:
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


def connect() -> sqlite3.Connection:
    """Open a new connection (schema is created/migrated once per process)."""
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    gi = config.DB_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")  # the index folder ignores itself
    con = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA synchronous=NORMAL")
    key = str(config.DB_PATH)
    if key not in _schema_ready:
        with _schema_lock:
            if key not in _schema_ready:
                _init_schema(con)
                _schema_ready.add(key)
    return con


def db() -> sqlite3.Connection:
    """Thread-local connection reused across queries (cheap: no reconnect per tool call)."""
    key = str(config.DB_PATH)
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "key", None) != key:
        if con is not None:
            con.close()
        con = connect()
        _local.con, _local.key = con, key
    return con


def close_db() -> None:
    con = getattr(_local, "con", None)
    if con is not None:
        con.close()
        _local.con = None


# --------------------------------------------------------------------------- file discovery
def _no_window() -> dict:
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def _git_files(root: Path):
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=60, **_no_window(),
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


def repo_files() -> list[str]:
    """All repo-relative posix paths (respects .gitignore when git is available)."""
    rels = _git_files(config.REPO_ROOT)
    if rels is None:
        rels = list(_walk_files(config.REPO_ROOT))
    tool_prefix = (config.TOOL_REL + "/") if config.TOOL_REL else None
    out = []
    for rel in rels:
        p = PurePosixPath(rel)
        if any(part in config.EXCLUDE_DIRS for part in p.parts[:-1]):
            continue
        if tool_prefix and rel.startswith(tool_prefix):
            continue
        out.append(rel)
    return out


def iter_source_files(all_files: list[str] | None = None):
    """Yield repo-relative posix paths of supported source files."""
    for rel in (repo_files() if all_files is None else all_files):
        if PurePosixPath(rel).suffix.lower() in config.LANG_BY_EXT:
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
_ROOT_CTX = Ctx(None, None, False)

_JS_FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
# Wrappers whose first function argument is "the" implementation: const X = memo(() => ...)
_JS_WRAPPERS = {"memo", "forwardRef", "useCallback", "useMemo", "observer", "debounce", "throttle",
                "createSelector", "asyncHandler", "defineComponent", "computed", "styled"}
# Bare calls that are language noise, not project code (kept out of the calls table).
_PY_BUILTINS = {n for n in dir(builtins) if not n.startswith("_")}
_JS_GLOBALS = {
    "require", "parseInt", "parseFloat", "String", "Number", "Boolean", "Symbol", "BigInt", "isNaN",
    "isFinite", "setTimeout", "clearTimeout", "setInterval", "clearInterval", "encodeURIComponent",
    "decodeURIComponent", "encodeURI", "decodeURI", "structuredClone", "queueMicrotask", "Array",
    "Object", "Date", "Error", "TypeError", "RangeError", "Map", "Set", "WeakMap", "WeakSet",
    "Promise", "RegExp", "URL", "URLSearchParams", "FormData", "Blob", "File", "Headers",
    "Request", "Response", "AbortController", "TextEncoder", "TextDecoder", "Uint8Array",
    "requestAnimationFrame", "cancelAnimationFrame", "fetch", "atob", "btoa",
}
# Subtrees that can never contain a symbol, import or call we record.
_SKIP_TYPES = {"string", "template_string", "comment", "number", "regex", "jsx_text",
               "string_fragment", "escape_sequence", "integer", "float", "type_annotation",
               "predefined_type", "true", "false", "none", "null", "undefined"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_PY_ROUTE_ATTRS = _HTTP_METHODS | {"api_route", "route", "websocket", "trace"}
_JS_ROUTER_RE = re.compile(r"^(app|server|router|routes?|[A-Za-z_$][\w$]*Router)$")
_NOISE_VARS = {"logger", "log", "LOGGER", "_logger", "_log", "__all__"}
_STR_PREFIX_RE = re.compile(r"^[rRbBuUfF]{0,2}")


def _unquote(s: str) -> str:
    s = _STR_PREFIX_RE.sub("", s.strip())
    for q in ('"""', "'''", '"', "'", "`"):
        if s.startswith(q) and s.endswith(q) and len(s) >= 2 * len(q):
            return s[len(q):-len(q)]
    return s.strip("'\"`")


def clean_doc(raw: str) -> str | None:
    """First meaningful line of a docstring / JSDoc / line comment, max ~120 chars."""
    s = _unquote(raw) if raw.lstrip()[:1] in "\"'rRbBuUfF" else raw
    for line in s.splitlines():
        line = line.strip().lstrip("/*#!").rstrip("*/").strip()
        if not line or line.startswith("@") or not re.search(r"[A-Za-z0-9]", line):
            continue
        line = " ".join(line.split())
        return line if len(line) <= 120 else line[:117] + "..."
    return None


class Extractor:
    """Walks a tree-sitter AST (iteratively) and collects symbols, imports, calls and routes."""

    def __init__(self, lang: str, src: bytes):
        self.lang = lang
        self.src = src
        self.symbols: list[tuple] = []
        self.imports: list[tuple] = []   # (module, names, line)
        self.calls: list[tuple] = []     # (caller, callee, receiver, line)
        self.routes: list[tuple] = []    # (method, path, handler, line)
        self.late_exports: set[str] = set()
        self.all_names: set[str] | None = None
        self.router_prefix: dict[str, str] = {}

    # ---- helpers
    def txt(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def name_of(self, node):
        nm = node.child_by_field_name("name")
        return self.txt(nm) if nm is not None else None

    def sig(self, node, body=None) -> str:
        end = body.start_byte if body is not None else min(node.end_byte, node.start_byte + 2000)
        s = self.src[node.start_byte:end].decode("utf-8", "replace")
        s = " ".join(s.split()).rstrip(" :{").rstrip()
        return s[:300]

    def add(self, node, name, kind, parent, signature, exported, outer=None, doc=None):
        outer = outer or node
        self.symbols.append((name, kind, parent, outer.start_point[0] + 1, outer.end_point[0] + 1,
                             signature, 1 if exported else 0, doc))

    @staticmethod
    def strip_quotes(s: str) -> str:
        return s.strip().strip("'\"`")

    def recv(self, obj):
        """Short receiver label for obj.method(): 'self', 'repo' (from self.repo), 'api'..."""
        if obj is None:
            return None
        t = obj.type
        if t in ("identifier", "this", "super", "self"):
            return self.txt(obj)[:40]
        if t == "attribute":
            a = obj.child_by_field_name("attribute")
            return self.txt(a)[:40] if a is not None else None
        if t == "member_expression":
            p = obj.child_by_field_name("property")
            return self.txt(p)[:40] if p is not None else None
        return None

    def comment_doc(self, outer):
        prev = outer.prev_named_sibling
        if prev is None or prev.type != "comment" or prev.end_point[0] < outer.start_point[0] - 1:
            return None
        text = self.txt(prev)
        if text.startswith("//"):  # walk up a contiguous block of // lines to its first line
            while True:
                p2 = prev.prev_named_sibling
                if (p2 is None or p2.type != "comment" or p2.end_point[0] != prev.start_point[0] - 1
                        or not self.txt(p2).startswith("//")):
                    break
                prev = p2
            text = self.txt(prev)
        elif not text.startswith("/**"):
            return None
        return clean_doc(text)

    def py_doc(self, body):
        if body is None:
            return None
        for c in body.named_children:
            if c.type == "comment":
                continue
            if c.type == "expression_statement" and c.named_child_count and c.named_children[0].type == "string":
                return clean_doc(self.txt(c.named_children[0]))
            return None
        return None

    # ---- traversal
    def run(self, root) -> None:
        visit = self.visit_python if self.lang == "python" else self.visit_js
        skip = _SKIP_TYPES
        stack = [(root, _ROOT_CTX)]
        pop, push = stack.pop, stack.append
        while stack:
            node, ctx = pop()
            child_ctx = visit(node, ctx)
            kids = node.named_children
            for i in range(len(kids) - 1, -1, -1):
                k = kids[i]
                if k.type not in skip:
                    push((k, child_ctx))
        if self.late_exports:
            self.symbols = [s[:6] + (1,) + s[7:] if s[2] is None and s[0] in self.late_exports else s
                            for s in self.symbols]
        if self.all_names is not None:
            self.symbols = [s[:6] + (1 if s[0] in self.all_names else 0,) + s[7:] if s[2] is None else s
                            for s in self.symbols]

    def result(self):
        return self.symbols, self.imports, self.calls, self.routes

    # ---- Python
    def visit_python(self, n, ctx: Ctx) -> Ctx:
        t = n.type
        if t == "class_definition" or t == "function_definition":
            name = self.name_of(n)
            if not name:
                return ctx
            parent = ctx.func or ctx.cls
            qual = f"{parent}.{name}" if parent else name
            outer = n.parent if n.parent is not None and n.parent.type == "decorated_definition" else n
            body = n.child_by_field_name("body")
            exported = parent is None and not name.startswith("_")
            if t == "class_definition":
                self.add(n, name, "class", parent, self.sig(n, body), exported, outer, self.py_doc(body))
                return Ctx(qual, None, False)
            kind = "method" if ctx.cls is not None and ctx.func is None else "function"
            self.add(n, name, kind, parent, self.sig(n, body), exported, outer, self.py_doc(body))
            if outer is not n:
                self.py_routes(outer, qual)
            return Ctx(ctx.cls, qual, False)

        if t == "call":
            f = n.child_by_field_name("function")
            if f is not None:
                caller = ctx.func or ctx.cls or "<module>"
                if f.type == "identifier":
                    callee = self.txt(f)
                    if callee not in _PY_BUILTINS:
                        self.calls.append((caller, callee, None, n.start_point[0] + 1))
                elif f.type == "attribute":
                    a = f.child_by_field_name("attribute")
                    if a is not None:
                        self.calls.append((caller, self.txt(a), self.recv(f.child_by_field_name("object")),
                                           n.start_point[0] + 1))
            return ctx

        if t == "import_statement":
            for c in n.named_children:
                if c.type == "dotted_name":
                    self.imports.append((self.txt(c), None, n.start_point[0] + 1))
                elif c.type == "aliased_import":
                    nm = c.child_by_field_name("name")
                    if nm is not None:
                        self.imports.append((self.txt(nm), None, n.start_point[0] + 1))
            return ctx

        if t == "import_from_statement":
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
                self.imports.append((module, ", ".join(names)[:300] or None, n.start_point[0] + 1))
            return ctx

        if t == "assignment" and ctx.func is None and ctx.cls is None:
            p = n.parent
            if p is not None and p.type == "expression_statement" and p.parent is not None \
                    and p.parent.type == "module":
                left = n.child_by_field_name("left")
                right = n.child_by_field_name("right")
                if left is not None and left.type == "identifier":
                    name = self.txt(left)
                    if name == "__all__" and right is not None:
                        self.all_names = {_unquote(self.txt(s)) for s in right.named_children
                                          if s.type == "string"}
                    elif name not in _NOISE_VARS:
                        self.add(n, name, "variable", None, self.sig(n)[:120], not name.startswith("_"), p)
                        self.py_router_prefix(name, right)
            return ctx
        return ctx

    def py_router_prefix(self, name: str, right) -> None:
        if right is None or right.type != "call":
            return
        f = right.child_by_field_name("function")
        if f is None or not self.txt(f).endswith(("APIRouter", "Blueprint", "Router")):
            return
        args = right.child_by_field_name("arguments")
        for a in (args.named_children if args is not None else []):
            if a.type == "keyword_argument":
                k, v = a.child_by_field_name("name"), a.child_by_field_name("value")
                if k is not None and v is not None and v.type == "string" \
                        and self.txt(k) in ("prefix", "url_prefix"):
                    self.router_prefix[name] = _unquote(self.txt(v))

    def py_routes(self, decorated, handler: str) -> None:
        for d in decorated.named_children:
            if d.type != "decorator":
                continue
            call = next((c for c in d.named_children if c.type == "call"), None)
            if call is None:
                continue
            f = call.child_by_field_name("function")
            if f is None or f.type != "attribute":
                continue
            attr_node = f.child_by_field_name("attribute")
            attr = self.txt(attr_node) if attr_node is not None else ""
            if attr not in _PY_ROUTE_ATTRS:
                continue
            args = call.child_by_field_name("arguments")
            path, methods = None, None
            for a in (args.named_children if args is not None else []):
                if a.type == "string" and path is None:
                    path = _unquote(self.txt(a))
                elif a.type == "keyword_argument":
                    k, v = a.child_by_field_name("name"), a.child_by_field_name("value")
                    if k is None or v is None:
                        continue
                    if self.txt(k) == "path" and v.type == "string":
                        path = _unquote(self.txt(v))
                    elif self.txt(k) == "methods":
                        methods = ",".join(_unquote(self.txt(s)).upper() for s in v.named_children
                                           if s.type == "string")
            if path is None:
                continue
            method = methods or {"websocket": "WS", "route": "GET", "api_route": "*"}.get(attr, attr.upper())
            obj = f.child_by_field_name("object")
            prefix = self.router_prefix.get(self.txt(obj), "") if obj is not None else ""
            self.routes.append((method, prefix + path, handler, d.start_point[0] + 1))

    # ---- JavaScript / TypeScript / TSX
    def js_func_value(self, val, depth: int = 0):
        """The function node behind `const X = <val>` (arrow, function, or memo(() => ...))."""
        if val is None or depth > 2:
            return None
        t = val.type
        if t in _JS_FUNC_VALUES:
            return val
        if t in ("as_expression", "satisfies_expression", "parenthesized_expression", "non_null_expression"):
            return self.js_func_value(val.named_children[0] if val.named_child_count else None, depth + 1)
        if t == "call_expression":
            f = val.child_by_field_name("function")
            if f is None:
                return None
            if f.type == "member_expression":
                f = f.child_by_field_name("property")
            if f is None or self.txt(f) not in _JS_WRAPPERS:
                return None
            args = val.child_by_field_name("arguments")
            for a in (args.named_children if args is not None else []):
                found = self.js_func_value(a, depth + 1)
                if found is not None:
                    return found
        return None

    def visit_js(self, n, ctx: Ctx) -> Ctx:
        t = n.type
        line = n.start_point[0] + 1

        if t == "call_expression":
            f = n.child_by_field_name("function")
            if f is None:
                return ctx
            caller = ctx.func or ctx.cls or "<module>"
            ft = f.type
            if ft == "identifier":
                callee = self.txt(f)
                if callee == "require":
                    args = n.child_by_field_name("arguments")
                    for a in (args.named_children if args is not None else []):
                        if a.type == "string":
                            self.imports.append((self.strip_quotes(self.txt(a)), "(require)", line))
                            break
                elif callee not in _JS_GLOBALS:
                    self.calls.append((caller, callee, None, line))
            elif ft == "member_expression":
                p = f.child_by_field_name("property")
                if p is not None:
                    prop = self.txt(p)
                    recv = self.recv(f.child_by_field_name("object"))
                    self.calls.append((caller, prop, recv, line))
                    if (prop in _HTTP_METHODS or prop == "all") and recv and _JS_ROUTER_RE.match(recv):
                        self.js_route(n, prop, ctx)
            elif ft == "import":  # dynamic import("x")
                args = n.child_by_field_name("arguments")
                for a in (args.named_children if args is not None else []):
                    if a.type == "string":
                        self.imports.append((self.strip_quotes(self.txt(a)), "(dynamic)", line))
                        break
            return ctx

        if t == "export_statement":
            src = n.child_by_field_name("source")
            if src is not None:
                self.imports.append((self.strip_quotes(self.txt(src)), "(re-export)", line))
            val = n.child_by_field_name("value")
            if val is not None:
                if val.type == "identifier":
                    self.late_exports.add(self.txt(val))
                elif val.type == "call_expression":  # export default memo(Foo)
                    args = val.child_by_field_name("arguments")
                    for a in (args.named_children if args is not None else []):
                        if a.type == "identifier":
                            self.late_exports.add(self.txt(a))
            return ctx._replace(exported=True)

        if t == "export_specifier":
            clause = n.parent
            stmt = clause.parent if clause is not None else None
            if stmt is not None and stmt.child_by_field_name("source") is None:
                nm = n.child_by_field_name("name")
                if nm is not None:
                    self.late_exports.add(self.txt(nm))
            return ctx

        if t == "import_statement":
            src = n.child_by_field_name("source")
            if src is not None:
                names = None
                for c in n.named_children:
                    if c.type == "import_clause":
                        names = " ".join(self.txt(c).split())[:300]
                        break
                self.imports.append((self.strip_quotes(self.txt(src)), names, line))
            return ctx

        if t == "new_expression":
            c = n.child_by_field_name("constructor")
            if c is not None:
                caller = ctx.func or ctx.cls or "<module>"
                if c.type == "identifier":
                    callee = self.txt(c)
                    if callee not in _JS_GLOBALS:
                        self.calls.append((caller, callee, None, line))
                elif c.type == "member_expression":
                    p = c.child_by_field_name("property")
                    if p is not None:
                        self.calls.append((caller, self.txt(p), self.recv(c.child_by_field_name("object")), line))
            return ctx

        parent = ctx.func or ctx.cls
        top = parent is None
        outer = n.parent if n.parent is not None and n.parent.type == "export_statement" else n

        if t in ("function_declaration", "generator_function_declaration"):
            name = self.name_of(n)
            if not name:
                return ctx._replace(exported=False)
            body = n.child_by_field_name("body")
            self.add(n, name, "function", parent, self.sig(n, body), top and ctx.exported, outer,
                     self.comment_doc(outer))
            return Ctx(ctx.cls, f"{parent}.{name}" if parent else name, False)

        if t in ("class_declaration", "abstract_class_declaration", "class"):
            name = self.name_of(n)
            if t == "class" and not (name and n.parent is not None and n.parent.type == "export_statement"):
                return ctx._replace(exported=False)
            if not name:
                return ctx._replace(exported=False)
            body = n.child_by_field_name("body")
            self.add(n, name, "class", parent, self.sig(n, body), top and ctx.exported, outer,
                     self.comment_doc(outer))
            return Ctx(f"{parent}.{name}" if parent else name, None, False)

        if t in _JS_FUNC_VALUES and top and n.parent is not None and n.parent.type == "export_statement":
            # export default function () {} / export default () => {}
            name = self.name_of(n) or "default"
            self.add(n, name, "function", None, self.sig(n, n.child_by_field_name("body")), True, n.parent,
                     self.comment_doc(n.parent))
            return Ctx(None, name, False)

        if t == "method_definition":
            name = self.name_of(n)
            if name and ctx.cls is not None and ctx.func is None:
                self.add(n, name, "method", ctx.cls, self.sig(n, n.child_by_field_name("body")), False, None,
                         self.comment_doc(n))
                return Ctx(ctx.cls, f"{ctx.cls}.{name}", False)
            return ctx._replace(exported=False)

        if t in ("public_field_definition", "field_definition"):
            nm = n.child_by_field_name("name") or n.child_by_field_name("property")
            fn = self.js_func_value(n.child_by_field_name("value"))
            if nm is not None and fn is not None and ctx.cls is not None and ctx.func is None:
                name = self.txt(nm)
                self.add(n, name, "method", ctx.cls, self.sig(n, fn.child_by_field_name("body")), False, None,
                         self.comment_doc(n))
                return Ctx(ctx.cls, f"{ctx.cls}.{name}", False)
            return ctx._replace(exported=False)

        if t == "pair":  # object-literal member:  getX: async (id) => ...
            if ctx.cls is not None and ctx.func is None:
                key = n.child_by_field_name("key")
                fn = self.js_func_value(n.child_by_field_name("value"))
                if key is not None and fn is not None:
                    name = self.strip_quotes(self.txt(key))
                    self.add(n, name, "method", ctx.cls, self.sig(n, fn.child_by_field_name("body")), False,
                             None, self.comment_doc(n))
                    return Ctx(ctx.cls, f"{ctx.cls}.{name}", False)
            return ctx._replace(exported=False)

        if t in ("interface_declaration", "enum_declaration"):
            name = self.name_of(n)
            if name and top:
                kind = "interface" if t == "interface_declaration" else "enum"
                self.add(n, name, kind, None, self.sig(n, n.child_by_field_name("body")), ctx.exported, outer,
                         self.comment_doc(outer))
            return ctx._replace(exported=False)

        if t == "type_alias_declaration":
            name = self.name_of(n)
            if name and top:
                self.add(n, name, "type", None, self.sig(n)[:200], ctx.exported, outer, self.comment_doc(outer))
            return ctx._replace(exported=False)

        if t == "variable_declarator":
            nm = n.child_by_field_name("name")
            if nm is None or nm.type != "identifier":
                return ctx._replace(exported=False)
            name = self.txt(nm)
            val = n.child_by_field_name("value")
            decl = n
            while decl.parent is not None and decl.parent.type in (
                    "lexical_declaration", "variable_declaration", "export_statement"):
                decl = decl.parent
            fn = self.js_func_value(val)
            if fn is not None:
                self.add(n, name, "function", parent, self.sig(n, fn.child_by_field_name("body")),
                         top and ctx.exported, decl, self.comment_doc(decl))
                return Ctx(ctx.cls, f"{parent}.{name}" if parent else name, False)
            if top:
                if val is not None and val.type == "object":
                    if ctx.exported or self._has_fn_members(val):
                        self.add(n, name, "variable", None, self.sig(n)[:120], ctx.exported, decl,
                                 self.comment_doc(decl))
                    return Ctx(name, None, False)  # members become methods of `name`
                if ctx.exported:
                    self.add(n, name, "variable", None, self.sig(n)[:160], True, decl, self.comment_doc(decl))
            return ctx._replace(exported=False)

        return ctx

    def _has_fn_members(self, obj) -> bool:
        for c in obj.named_children:
            if c.type == "method_definition":
                return True
            if c.type == "pair" and self.js_func_value(c.child_by_field_name("value")) is not None:
                return True
        return False

    def js_route(self, n, prop: str, ctx: Ctx) -> None:
        args = n.child_by_field_name("arguments")
        named = args.named_children if args is not None else []
        if len(named) < 2 or named[0].type != "string":
            return
        path = self.strip_quotes(self.txt(named[0]))
        if not path.startswith("/"):
            return
        last = named[-1]
        if last.type == "identifier":
            handler = self.txt(last)
        elif last.type == "member_expression":
            p = last.child_by_field_name("property")
            handler = self.txt(p) if p is not None else "<inline>"
        else:
            handler = "<inline>"
        self.routes.append(("*" if prop == "all" else prop.upper(), path, handler, n.start_point[0] + 1))


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def parse_source(lang: str, data: bytes):
    """Return (symbols, imports, calls, routes) or None. Pure: safe to run in a worker process."""
    if _is_binary(data):
        return None
    parser = get_parser(lang)
    if parser is None:
        return None
    ex = Extractor(lang, data)
    ex.run(parser.parse(data).root_node)
    return ex.result()


def _parse_job(job):
    rel, lang, data = job
    try:
        return rel, parse_source(lang, data), None
    except Exception as e:  # never let one bad file kill a batch
        return rel, None, str(e)


# --------------------------------------------------------------------------- indexing
def _write_file(con: sqlite3.Connection, rel: str, lang: str, data: bytes, digest: str,
                st: os.stat_result, result) -> None:
    line_count = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    for table in _PER_FILE_TABLES:
        con.execute(f"DELETE FROM {table} WHERE file=?", (rel,))
    con.execute(
        "INSERT OR REPLACE INTO files(path, lang, hash, mtime, size, line_count, indexed_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (rel, lang, digest, st.st_mtime_ns, st.st_size, line_count, time.time()),
    )
    if result is None:
        return
    symbols, imports, calls, routes = result
    con.executemany(
        "INSERT INTO symbols(file,name,kind,parent,line_start,line_end,signature,exported,doc) "
        "VALUES(?,?,?,?,?,?,?,?,?)", [(rel, *s) for s in symbols])
    con.executemany("INSERT INTO imports(file,module,names,line) VALUES(?,?,?,?)",
                    [(rel, *i) for i in imports])
    con.executemany("INSERT INTO calls(file,caller,callee,receiver,line) VALUES(?,?,?,?,?)",
                    [(rel, *c) for c in calls])
    con.executemany("INSERT INTO routes(file,method,path,handler,line) VALUES(?,?,?,?,?)",
                    [(rel, *r) for r in routes])


def index_file(con: sqlite3.Connection, rel: str, data: bytes, digest: str, st: os.stat_result) -> None:
    lang = config.LANG_BY_EXT.get(PurePosixPath(rel).suffix.lower(), "")
    rel_, result, err = _parse_job((rel, lang, data))
    if err:
        log(f"parse error in {rel}: {err}")
    _write_file(con, rel, lang, data, digest, st, result)


_BATCH = 256
_PARALLEL_MIN = 2000  # measured: at ~750 files, process start-up still costs more than it saves


def _make_pool(n_files: int):
    if n_files < _PARALLEL_MIN or config.WORKERS <= 1:
        return None
    try:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        return ProcessPoolExecutor(max_workers=config.WORKERS, mp_context=multiprocessing.get_context("spawn"))
    except Exception as e:
        log(f"parallel parsing unavailable ({e}); parsing in-process")
        return None


def sync(full: bool = False) -> dict:
    """Bring the index up to date. Cheap when nothing changed: a stat() per file, and a
    content hash + re-parse only for files whose mtime/size changed."""
    con = connect()
    pool = None
    try:
        known = {r["path"]: r for r in con.execute("SELECT path, hash, mtime, size FROM files")}
        seen: set[str] = set()
        stats = {"scanned": 0, "reindexed": 0, "removed": 0, "skipped_large": 0}
        all_files = repo_files()
        todo = []
        for rel in iter_source_files(all_files):
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
            todo.append((rel, st, row))

        pool = _make_pool(len(todo))
        for i in range(0, len(todo), _BATCH):
            jobs, meta = [], {}
            for rel, st, row in todo[i:i + _BATCH]:
                try:
                    data = (config.REPO_ROOT / rel).read_bytes()
                except OSError:
                    seen.discard(rel)
                    continue
                digest = hashlib.sha1(data).hexdigest()
                if not full and row and row["hash"] == digest:
                    con.execute("UPDATE files SET mtime=?, size=? WHERE path=?", (st.st_mtime_ns, st.st_size, rel))
                    continue
                lang = config.LANG_BY_EXT.get(PurePosixPath(rel).suffix.lower(), "")
                jobs.append((rel, lang, data))
                meta[rel] = (lang, data, digest, st)
            results = pool.map(_parse_job, jobs, chunksize=8) if pool else map(_parse_job, jobs)
            for rel, result, err in results:
                if err:
                    log(f"parse error in {rel}: {err}")
                lang, data, digest, st = meta[rel]
                _write_file(con, rel, lang, data, digest, st, result)
                stats["reindexed"] += 1

        for rel in set(known) - seen:
            for table in _PER_FILE_TABLES:
                con.execute(f"DELETE FROM {table} WHERE file=?", (rel,))
            con.execute("DELETE FROM files WHERE path=?", (rel,))
            stats["removed"] += 1

        if stats["reindexed"] or stats["removed"] or full \
                or con.execute("SELECT value FROM meta WHERE key='deps_built'").fetchone() is None:
            resolve_deps(con, all_files)
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('deps_built', '1')")
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_sync_at', ?)", (str(time.time()),))
        head = _git_head()
        if head:
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('git_head', ?)", (head,))
        con.commit()
        return stats
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
        con.close()


# --------------------------------------------------------------------------- import resolution
_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".d.ts")


def _load_jsonc(text: str):
    """json.loads for tsconfig-style JSON (comments + trailing commas)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def _norm(p: str) -> str:
    p = posixpath.normpath(p) if p else ""
    return "" if p == "." else p


def _ts_alias_rules(all_files: list[str]) -> list[tuple]:
    """[(scope_dir, pattern_prefix, wildcard, [target_dirs])] from every tsconfig/jsconfig."""
    rules = []
    for rel in all_files:
        base = posixpath.basename(rel)
        if not ((base.startswith("tsconfig") and base.endswith(".json")) or base == "jsconfig.json"):
            continue
        try:
            cfg = _load_jsonc((config.REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        opts = (cfg or {}).get("compilerOptions") or {}
        cdir = posixpath.dirname(rel)
        base_url = _norm(posixpath.join(cdir, opts.get("baseUrl", ".")))
        for pat, targets in (opts.get("paths") or {}).items():
            wild = pat.endswith("*")
            tdirs = [_norm(posixpath.join(base_url, t.rstrip("*"))) for t in targets if isinstance(t, str)]
            rules.append((cdir, pat.rstrip("*"), wild, tdirs))
        if "baseUrl" in opts:
            rules.append((cdir, "", True, [base_url]))
    rules.sort(key=lambda r: (-len(r[0]), -len(r[1])))  # deepest scope, longest pattern first
    return rules


class _Resolver:
    def __init__(self, all_files: list[str], indexed: set[str]):
        self.files = indexed
        self.rules = _ts_alias_rules(all_files)
        self.py_mod: dict[str, list[str]] = {}
        self.js_noext: dict[str, list[str]] = {}
        for p in indexed:
            if p.endswith(".py"):
                parts = p[:-3].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                for i in range(len(parts)):
                    self.py_mod.setdefault(".".join(parts[i:]), []).append(p)
            else:
                stem = re.sub(r"\.[^./]+$", "", p)
                self.js_noext.setdefault(stem, []).append(p)
                if stem.endswith("/index"):
                    self.js_noext.setdefault(stem[:-6], []).append(p)

    # ---- JavaScript / TypeScript
    def js_find(self, base: str):
        base = _norm(base)
        if base in self.files:
            return base
        stem = re.sub(r"\.(js|jsx|mjs|cjs)$", "", base)
        for cand in (stem, base):
            for ext in _JS_EXTS:
                if cand + ext in self.files:
                    return cand + ext
            for ext in _JS_EXTS:
                if cand + "/index" + ext in self.files:
                    return cand + "/index" + ext
        return None

    def js(self, src: str, spec: str):
        if spec.startswith("."):
            return self.js_find(posixpath.join(posixpath.dirname(src), spec))
        for scope, prefix, wild, targets in self.rules:
            if scope and not src.startswith(scope + "/"):
                continue
            if wild:
                if not spec.startswith(prefix):
                    continue
                rest = spec[len(prefix):]
            elif spec != prefix:
                continue
            else:
                rest = ""
            for tdir in targets:
                hit = self.js_find(posixpath.join(tdir, rest) if rest else tdir)
                if hit:
                    return hit
        if spec[:2] in ("@/", "~/", "#/"):  # alias without a tsconfig we could read: unique suffix match
            rest = spec[2:]
            cands = [p for k, ps in self.js_noext.items() if k == rest or k.endswith("/" + rest) for p in ps]
            if len(set(cands)) == 1:
                return cands[0]
        return None

    # ---- Python
    def py_abs(self, src: str, module: str):
        cands = self.py_mod.get(module)
        if not cands:
            return None
        nseg = module.count(".") + 1
        src_dir = posixpath.dirname(src)
        good = []
        for c in cands:
            parts = c[:-3].split("/")
            drop = nseg + (1 if parts[-1] == "__init__" else 0)
            root = "/".join(parts[:-drop]) if len(parts) > drop else ""
            if root == "" or src_dir == root or src_dir.startswith(root + "/"):
                good.append((len(root), c))
        if good:
            return max(good)[1]
        return cands[0] if nseg > 1 and len(cands) == 1 else None

    def py_rel(self, src: str, module: str):
        level = len(module) - len(module.lstrip("."))
        rest = module[level:]
        base = posixpath.dirname(src)
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        path = _norm(posixpath.join(base, rest.replace(".", "/"))) if rest else base
        for cand in (path + ".py", (path + "/" if path else "") + "__init__.py"):
            if cand in self.files:
                return cand
        return None

    def py(self, src: str, module: str, names: str | None) -> list[str]:
        find = self.py_rel if module.startswith(".") else self.py_abs
        out = []
        m = find(src, module)
        if m:
            out.append(m)
        for n in (names or "").split(","):
            n = n.strip()
            if n and n != "*" and n.isidentifier():
                sub = find(src, module + ("" if module.endswith(".") else ".") + n)
                if sub:
                    out.append(sub)
        return out


def resolve_deps(con: sqlite3.Connection, all_files: list[str] | None = None) -> None:
    """Rebuild the file -> file dependency table from raw import rows."""
    indexed = {r["path"] for r in con.execute("SELECT path FROM files")}
    res = _Resolver(all_files if all_files is not None else repo_files(), indexed)
    rows = con.execute("SELECT i.file, i.module, i.names, f.lang FROM imports i JOIN files f ON f.path = i.file")
    edges = {}
    for r in rows:
        src, module = r["file"], r["module"]
        targets = res.py(src, module, r["names"]) if r["lang"] == "python" else [res.js(src, module)]
        for dst in targets:
            if dst and dst != src:
                edges.setdefault((src, dst), module)
    con.execute("DELETE FROM deps")
    con.executemany("INSERT INTO deps(src, dst, module) VALUES(?,?,?)", [(s, d, m) for (s, d), m in edges.items()])


# --------------------------------------------------------------------------- git + freshness
def _git_dir(root: Path):
    g = root / ".git"
    if g.is_dir():
        return g
    if g.is_file():  # worktree / submodule: "gitdir: <path>"
        try:
            text = g.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            p = Path(text.split(":", 1)[1].strip())
            return p if p.is_absolute() else (root / p).resolve()
    return None


def _git_head() -> str:
    """Current branch ref + commit, so a checkout/pull is visible in the stored index."""
    gd = _git_dir(config.REPO_ROOT)
    if gd is None:
        return ""
    try:
        text = (gd / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text.startswith("ref:"):
        return text
    ref = text.split(":", 1)[1].strip()
    common = gd
    try:
        cd = (gd / "commondir").read_text(encoding="utf-8").strip()
        common = (gd / cd).resolve()
    except OSError:
        pass
    for base in (gd, common):
        try:
            return f"{ref} {(base / ref).read_text(encoding='utf-8', errors='replace').strip()}"
        except OSError:
            pass
    try:
        for line in (common / "packed-refs").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.endswith(" " + ref) and not line.startswith(("#", "^")):
                return f"{ref} {line.split(' ', 1)[0]}"
    except OSError:
        pass
    return ref


_lock = threading.Lock()
_last_sync = 0.0
_watch_interval = 0.0
_watch_stop = threading.Event()


def refresh(full: bool = False) -> dict:
    """sync() under the process-wide lock (safe to call while the watcher runs)."""
    global _last_sync
    with _lock:
        result = sync(full=full)
        _last_sync = time.monotonic()
        return result


def ensure_fresh(min_interval: float = 1.5):
    """Called at the start of every MCP tool call so uncommitted edits are always indexed.

    When the background watcher is running it already re-scans every few seconds, so a tool
    call only re-syncs if the watcher has not done so recently."""
    global _last_sync
    if _watch_interval > 0:
        min_interval = max(min_interval, _watch_interval + 1.0)
    with _lock:
        if time.monotonic() - _last_sync < min_interval:
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
    global _watch_interval
    if interval is None:
        interval = config.WATCH_INTERVAL
    if interval <= 0:
        return
    with _lock:
        if _watch_interval > 0:
            return
        _watch_interval = interval

    def loop() -> None:
        global _last_sync
        first = True
        while first or not _watch_stop.wait(interval):
            first = False
            try:
                with _lock:
                    result = sync()
                    _last_sync = time.monotonic()
                if result["reindexed"] or result["removed"]:
                    log(f"auto-refresh reindexed={result['reindexed']} removed={result['removed']} "
                        f"scanned={result['scanned']}")
            except Exception as e:
                log(f"auto-refresh failed: {e}")

    threading.Thread(target=loop, name="codebase-index-watch", daemon=True).start()
    log(f"watching {config.REPO_ROOT} every {interval:g}s -> {config.DB_PATH}")
