---
name: code-graph-analyzer
description: Pre-index the SUT into a code knowledge graph (CodeGraphContext free / gitnexus paid / tree-sitter fallback) and query it lazily for routes, models, handlers, callers, callees, and request/response shapes. Replaces whole-file reads with targeted graph queries — massive token savings for source-code-audit and source-aware-test-gen. GraphProvider ABC + GraphQueryClient + StackDetector + GraphIndexer + CodeGraphInstaller. Activate when the user says "index codebase", "code graph", "analyze sut", "detect stack", or before running source-code-audit on a large repo.
---

# Code Graph Analyzer — Lazy Source Context for the Flagship Chain

**The token-savings skill for the flagship chain.** Most of the cost in `source-code-audit` → `arch-*` → `source-aware-test-gen` is spent reading SUT files. This skill pre-indexes the SUT into a graph *once*, then lets downstream skills pull only the symbols they need (one route handler, one Pydantic model) instead of whole files or whole directories.

Three backends are supported behind a single `GraphProvider` ABC:

1. `CodeGraphContextProvider` — free, neo4j-backed MCP server. Auto-install on first run.
2. `GitNexusProvider` — paid MCP (`mcp__gitnexus__*` tools). Richer impact analysis.
3. `TreeSitterProvider` — pure-python, no daemon. Fallback when no MCP is installed.

A thin `GraphQueryClient` exposes a stable query API so `source-code-audit` and `source-aware-test-gen` don't care which backend is behind it.

## When to Activate

- Before `source-code-audit` on any repo > 500 files or > 200K LoC.
- User says "index codebase", "build a code graph", "analyze sut", "detect stack".
- When `source-aware-test-gen` is about to generate 20+ tests — call `GraphQueryClient.get_function_source(...)` per test rather than re-reading entire handlers.
- Monorepos where `Path.read_text()` on the whole tree would blow the context window.

## Emitted Tree

```
tests/framework/codegraph/
├── __init__.py
├── dataclasses.py           # RouteInfo / FunctionRef / PydanticModelRef / ORMEntityRef / DetectedStack / RequestResponseShape
├── graph_provider.py        # GraphProvider ABC + 3 concretes
├── graph_query_client.py    # GraphQueryClient — high-level API
├── graph_indexer.py         # GraphIndexer — one-shot + incremental refresh
├── stack_detector.py        # StackDetector + DetectedStack + recommend_chain()
└── installer.py             # CodeGraphInstaller — uv tool install / pipx install
```

## Value Objects

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(slots=True, frozen=True)
class FunctionRef:
    """A function or method as seen by the graph."""
    qualified_name: str                      # "app.api.users.create_user"
    file: Path
    lineno: int
    end_lineno: int
    is_async: bool = False
    is_method: bool = False
    decorators: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class RouteInfo:
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    path: str                                # "/api/v1/users/{user_id}"
    handler: FunctionRef
    framework: Literal["fastapi", "flask", "django", "starlette", "aiohttp"]
    request_model: str | None = None         # qualified name
    response_model: str | None = None
    status_codes: tuple[int, ...] = (200,)
    auth: Literal["public", "bearer", "basic", "api_key", "cookie", "session"] = "public"


@dataclass(slots=True, frozen=True)
class PydanticModelRef:
    qualified_name: str
    file: Path
    lineno: int
    pydantic_version: Literal["v1", "v2"]
    fields: tuple[tuple[str, str], ...] = ()  # ((name, annotation), ...)
    is_input: bool = False
    is_output: bool = False


@dataclass(slots=True, frozen=True)
class ORMEntityRef:
    qualified_name: str
    file: Path
    table_name: str
    orm: Literal["sqlalchemy", "django", "tortoise", "peewee"]
    fields: tuple[tuple[str, str], ...] = ()
    relations: tuple[tuple[str, str], ...] = ()  # ((name, target), ...)


@dataclass(slots=True, frozen=True)
class RequestResponseShape:
    route: RouteInfo
    request_example: dict | None = None
    response_example: dict | None = None
    error_examples: tuple[dict, ...] = ()


@dataclass(slots=True, frozen=True)
class DetectedStack:
    """What the repo actually uses. Consumed by every arch-* skill."""
    backend: tuple[str, ...] = ()            # fastapi / flask / django / starlette
    orm: tuple[str, ...] = ()                # sqlalchemy / django-orm
    pydantic: Literal["v1", "v2", "none"] = "none"
    messaging: tuple[str, ...] = ()          # kafka-python / aiokafka / confluent-kafka / pika / aio-pika / celery
    streams: tuple[str, ...] = ()            # websockets / fastapi-websocket / sse-starlette
    http_clients: tuple[str, ...] = ()       # httpx / requests / aiohttp
    analytics: tuple[str, ...] = ()          # clickhouse-driver / clickhouse-connect
    rpc: tuple[str, ...] = ()                # grpcio / graphene / strawberry / sgqlc
    async_runtime: tuple[str, ...] = ()      # asyncio / trio
    frontend: tuple[str, ...] = ()           # next.js / react / vue
```

## GraphProvider ABC + Concretes

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self


class GraphProvider(ABC):
    """Backend-agnostic contract for a code knowledge graph."""

    name: str

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def ensure_installed(self) -> Self: ...

    @abstractmethod
    def index(self, root: Path) -> Self: ...

    @abstractmethod
    def query(self, query: str, **params) -> list[dict]: ...

    @abstractmethod
    def cypher(self, cypher: str, **params) -> list[dict]: ...


class CodeGraphContextProvider(GraphProvider):
    """Free, neo4j-backed MCP — auto-installs on first call."""
    name = "codegraphcontext"
    # see templates/graph_provider.py


class GitNexusProvider(GraphProvider):
    """Paid MCP. Uses mcp__gitnexus__{list_repos, query, cypher, context,
    impact, route_map, shape_check, tool_map, rename, api_impact}."""
    name = "gitnexus"


class TreeSitterProvider(GraphProvider):
    """No-daemon fallback. tree-sitter + networkx for a light in-process graph."""
    name = "tree-sitter"
```

## GraphQueryClient — the Only Surface Downstream Skills See

```python
class GraphQueryClient:
    """High-level query API. Downstream skills get RouteInfo / FunctionRef /
    PydanticModelRef objects — never raw Cypher, never whole-file reads."""

    def __init__(self, provider: GraphProvider) -> None:
        self._provider = provider

    @allure.step("Graph.find_routes")
    def find_routes(self) -> list[RouteInfo]: ...

    @allure.step("Graph.find_handlers_for_route({path})")
    def find_handlers_for_route(self, path: str) -> list[FunctionRef]: ...

    @allure.step("Graph.find_models")
    def find_models(self) -> list[PydanticModelRef]: ...

    @allure.step("Graph.find_orm_entities")
    def find_orm_entities(self) -> list[ORMEntityRef]: ...

    @allure.step("Graph.find_callers({symbol})")
    def find_callers(self, symbol: str) -> list[FunctionRef]: ...

    @allure.step("Graph.find_callees({symbol})")
    def find_callees(self, symbol: str) -> list[FunctionRef]: ...

    @allure.step("Graph.get_function_source({symbol})")
    def get_function_source(self, symbol: str) -> str: ...

    @allure.step("Graph.get_class_source({symbol})")
    def get_class_source(self, symbol: str) -> str: ...

    @allure.step("Graph.shape_of({endpoint})")
    def shape_of(self, endpoint: str) -> RequestResponseShape: ...
```

## GraphIndexer

```python
class GraphIndexer:
    """One-shot .index(root) and .refresh() for changed files only."""

    def __init__(self, provider: GraphProvider) -> None:
        self._provider = provider

    @allure.step("Graph.index({root})")
    def index(self, root: Path) -> Self: ...

    @allure.step("Graph.refresh({root})")
    def refresh(self, root: Path, since: str = "HEAD~1") -> Self: ...
```

## StackDetector — Routes the Whole Chain

Every `arch-*` skill and `source-code-audit` calls `StackDetector.detect(root)` *first* to decide which chain to run. Detection is cheap: scans `requirements*.txt`, `pyproject.toml`, `package.json`, plus first-party imports.

```python
class StackDetector:
    """Scans imports + manifests to decide which arch-* skills to invoke."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @allure.step("StackDetector.detect")
    def detect(self) -> DetectedStack: ...

    @allure.step("StackDetector.recommend_chain")
    def recommend_chain(self, stack: DetectedStack) -> list[str]:
        """Map DetectedStack → ordered list of skill names to invoke.

        Examples:
          fastapi + pydantic v2 + httpx → [arch-service-object-rest, source-aware-test-gen]
          strawberry / graphene         → [arch-service-object-graphql, ...]
          grpcio                        → [arch-service-object-grpc, ...]
          kafka-python / aiokafka       → [arch-kafka-testing, ...]
          clickhouse-driver / -connect  → [arch-clickhouse-testing, ...]
          next.js + react + data-testid → [arch-playwright-pom, arch-page-components, ...]
        """
```

## Installation Bootstrap

If `CodeGraphContextProvider.is_available()` returns False, `CodeGraphInstaller` runs the right bootstrap command for the user's environment.

```python
class CodeGraphInstaller:
    """Installs CodeGraphContext (free, neo4j-based MCP) on first use.

    Resolution order:
      1. `uv tool install codegraphcontext`  (preferred — isolated venv)
      2. `pipx install codegraphcontext`      (fallback — also isolated)
      3. `python -m pip install --user codegraphcontext` (last resort)

    Also verifies:
      - neo4j daemon reachable (bolt://localhost:7687) or docker-compose present
      - `codegraphcontext --version` prints
    Prints the user's config block for `.mcp.json` / `~/.claude/mcp.json`.
    """

    def ensure_installed(self) -> Self: ...
    def print_mcp_config(self) -> None: ...
    def start_neo4j_if_needed(self) -> Self: ...
```

## Integration with the Flagship Chain

Before — `source-code-audit` reads every file under `src/`:

```python
# OLD: token-heavy
for file in root.rglob("*.py"):
    content = file.read_text()           # 1.2M tokens on a 2000-file repo
    extract_routes(content)
    extract_models(content)
```

After — a single index, then targeted queries:

```python
# NEW: token-light
provider = CodeGraphContextProvider().ensure_installed()
GraphIndexer(provider).index(root)
client = GraphQueryClient(provider)

routes = client.find_routes()                       # structured, already parsed
for route in routes:
    shape = client.shape_of(route.path)             # only this endpoint
    handler_src = client.get_function_source(route.handler.qualified_name)
    # feed just these bytes into source-aware-test-gen
```

`source-aware-test-gen` equivalent:

```python
for target in test_matrix.p0:
    src = client.get_function_source(target.handler)     # ~30 lines, not 300
    callees = client.find_callees(target.handler)
    side_effects = [c for c in callees if c.qualified_name.startswith("app.events")]
    write_test(target, src, side_effects)
```

## Token Savings (illustrative)

| Repo size | Skill | Before (read_text) | After (graph) | Savings |
|-----------|-------|-------------------:|--------------:|--------:|
| 200 files, 50K LoC FastAPI | source-code-audit | 180K tok | 22K tok | 88% |
| 2,000 files, 500K LoC Django | source-code-audit | 1.2M tok | 80K tok | 93% |
| 500 files, 120K LoC FastAPI | source-aware-test-gen (40 tests) | 420K tok | 55K tok | 87% |
| 2,000 files, monorepo | arch-* stack detection | 260K tok | 6K tok | 97% |

Numbers are illustrative — actual savings depend on repo shape. The mechanism is the same in all cases: one index up-front, targeted queries per test.

## Example — End-to-End

**User says:** "Index /Users/me/Code/my-saas and generate tests for the P0 routes."

Skill does:

1. `CodeGraphInstaller().ensure_installed()` — installs CodeGraphContext via `uv tool install` if absent, starts neo4j via docker compose if needed.
2. `StackDetector(root).detect()` → `DetectedStack(backend=("fastapi",), pydantic="v2", orm=("sqlalchemy",), http_clients=("httpx",), frontend=("next.js",))`.
3. `StackDetector.recommend_chain(stack)` → `[arch-service-object-rest, arch-playwright-pom, source-aware-test-gen]`.
4. `GraphIndexer(provider).index(root)` — one pass, ~45s for 500 files.
5. `source-code-audit` consumes `GraphQueryClient`: 22K tokens total vs 180K of raw reads.
6. `source-aware-test-gen` pulls per-target handler + models via `get_function_source()` / `find_models()`.
7. Hands off `artifacts/source-inventory.json` enriched with graph-verified references.

## Common Pitfalls

- **Stale index** — run `GraphIndexer.refresh(root, since="HEAD~1")` after any `git pull` on the SUT. A stale graph yields tests against routes that no longer exist.
- **git-lfs private repos** — the free provider skips LFS pointers silently; validate a known file resolves before trusting the index.
- **Monorepo scoping** — always pass the specific service root (e.g. `repos/billing-svc/`) rather than the monorepo top. Per-service indices stay small and fresh.
- **Daemon not running** — `CodeGraphContextProvider` needs neo4j on `bolt://localhost:7687`. `CodeGraphInstaller.start_neo4j_if_needed()` brings up a docker compose file; without docker the provider errors out — fall back to `TreeSitterProvider`.
- **Version skew** — the provider encodes schema assumptions. On version bump, drop and re-index; don't try to migrate incrementally.
- **Python version** — `TreeSitterProvider` needs grammar wheels for the interpreter in use: check that the grammar package imports on the running interpreter before indexing, and fall back to another provider if it does not.
- **Don't query Cypher from downstream skills** — always go through `GraphQueryClient`. Raw Cypher makes the skill pipeline brittle across providers.

## Related Skills

- `source-code-audit` — mandatory consumer: replaces its whole-file reads with `GraphQueryClient` calls.
- `source-aware-test-gen` — consumer: `get_function_source()` / `find_models()` per test.
- `arch-service-object-rest` / `arch-service-object-graphql` / `arch-service-object-grpc` — read `DetectedStack` to decide which one to scaffold.
- `arch-playwright-pom` / `arch-page-components` — triggered when `DetectedStack.frontend` is non-empty.
- `arch-kafka-testing` / `arch-clickhouse-testing` — triggered on `DetectedStack.messaging` / `DetectedStack.analytics`.
- `coverage-gap-finder` — can join graph churn with coverage to rank hotspots more precisely.
- `production-error-to-regression-test` — uses `find_callers()` to locate the failing frame's surrounding context cheaply.
