# Tools reference

All tools return **compact plain text**, one fact per line (not JSON), so they cost few tokens. Each call
first makes sure the index is fresh. The same queries are available in a terminal as `codebase-index <command>`.

| Tool | CLI | Arguments |
|---|---|---|
| `repo_map` | `map [path]` | `path=""`, `limit=30` |
| `search_symbol` | `search "<q>"` | `query`, `kind=""` (function\|method\|class\|interface\|type\|enum\|variable), `limit=20` |
| `get_file_summary` | `summary <file>` | `file`, `depth=1` (2 shows nested functions) |
| `get_exports` | `exports <file>` | `file` |
| `read_symbol_source` | `source <symbols>` | `file=""`, `symbol=""`, `line_start=0`, `line_end=0`, `mode="auto"` (auto\|full\|skeleton) |
| `find_callers` | `callers <symbol>` | `symbol`, `receiver=""`, `depth=1` (up to 3), `limit=30` |
| `find_callees` | `callees <symbol>` | `symbol`, `file=""`, `limit=40` |
| `who_imports` | `importers <file>` | `file`, `limit=40` |
| `find_route` | `routes [query]` | `query=""`, `method=""`, `limit=50` |
| `summarize_file` | `ask <file> "<q>"` | `file`, `question`, `line_start=0`, `line_end=0` (needs an API key) |
| `reindex` | `index [--full]` | `full=false` |
| `index_stats` | `stats` | none |

## Example output

From the test fixture in `tests/test_index.py`:

```text
> search_symbol("UserService.save, getUser")
"UserService.save": 1 match
pkg/service.py:16-22 method UserService.save(self, user)  # Persist a user.

"getUser": 1 match
web/src/lib/api.ts:3-3 method api.getUser: async (id: string) =>

> get_file_summary("pkg/service.py")
pkg/service.py (python, 32 lines, 7 symbols; * = exported)
imports: .models, fastapi, pkg
routes: GET /users/{user_id} -> list_users
L6-6 router = APIRouter(prefix="/users")
L10-22 *class UserService  # Manages users.
  L13-14 def __init__(self, repo)
  L16-22 def save(self, user)  # Persist a user.
L25-28 *def list_users(user_id: int)
L31-32 def _private()
(+1 deeper nested symbols; pass depth=2 to show)

> find_callers("check", depth=2)
callers of check: 1 call sites in 1 files
defined: check pkg/util.py:1
pkg/service.py: L19 UserService.save._validate via util
transitive callers (up to depth 2):
  UserService.save._validate <- pkg/service.py:20 UserService.save

> read_symbol_source(symbol="Panel", mode="skeleton")
== web/src/components/Panel.tsx:5-17 Panel (13 lines) skeleton (folded blocks: read them with line_start/line_end)
export const Panel = forwardRef(function Panel(props: any, ref: any) {
  const [a, setA] = useState(0);
  const handleClick = useCallback(() => {
    ... L8-14 folded (7 lines)
  }, []);
  return <div onClick={handleClick}>{a}</div>;
});
```

`mode="auto"` (default) returns full source when it fits in 300 lines and the skeleton otherwise. A skeleton
keeps short statements verbatim and folds long ones to `... L1192-1217 folded (26 lines)`; read just those
ranges with `line_start` / `line_end`.

## Output conventions

- Locations are `path:start-end` (1-based, inclusive). Paths are repo-relative and `/`-separated.
- `*` marks exported/public symbols (Python: not `_`-prefixed, or listed in `__all__`; JS/TS: `export`).
- `# ...` after a line is the first docstring / JSDoc line.
- Nested symbols are qualified: `Class.method`, `Component.handleClick`, `outer.inner`.
- `via X` in `find_callers` is the receiver: `self.repo.save()` → `via repo`.

## Query syntax for `search_symbol`

| Query | Matches |
|---|---|
| `save` | any symbol whose name contains `save` |
| `UserService.save` | `save` whose parent is `UserService` |
| `UserService.` | all members of `UserService` |
| `accept evidence` | `acceptEvidence`, `accept_evidence`, `AcceptEvidence` |
| `a, b, c` | three searches in one round trip |

## Accuracy

Results are exact for **what is defined where**, and name-based for **who calls whom**. `find_callers`
matches by function name, shows the receiver, and warns when several definitions share a name: check the
receiver and file before a large refactor. See [known limits](../README.md#known-limits).
