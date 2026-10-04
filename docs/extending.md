# Extending: add a language

1. `pip install tree-sitter-<lang>` and add it to `dependencies` in `pyproject.toml`.
2. `src/codebase_index/config.py`: map the extensions in `LANG_BY_EXT` (e.g. `".go": "go"`).
3. `indexer.get_parser`: load the grammar (`Language(tree_sitter_go.language())`).
4. `indexer.Extractor`: add `visit_<lang>(self, node, ctx) -> ctx` and select it in `run()`. Record symbols
   with `self.add(...)`, imports with `self.imports.append((module, names, line))`, calls with
   `self.calls.append((caller, callee, receiver, line))`. Return a new `Ctx(cls, func, exported)` when
   entering a class/function so nested items get the right parent.
5. `indexer._Resolver`: optionally teach it the language's import paths so `who_imports` resolves them.
6. Add a fixture file and assertions to `tests/test_index.py`.
7. Add the language to the tables in `docs/how-it-works.md` and the README.

Use the [tree-sitter playground](https://tree-sitter.github.io/tree-sitter/7-playground.html) or
`print(tree.root_node)` to see node and field names.

## Adding a client to `setup`

`src/codebase_index/clients.py` has one `setup_<client>(...)` function per client and a `SETUP` table.
Merge JSON with `Writer.merge_json`, edit Markdown with `Writer.md_block`, and return a list of
"next step" lines. Add a test in `tests/test_setup.py` (idempotent, merges, `--dry-run` writes nothing).
