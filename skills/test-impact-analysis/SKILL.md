---
name: test-impact-analysis
description: OOP diff-aware test selection — GitDiffLoader parses `git diff --name-only`, ImpactedSymbolResolver maps changed files → symbols → downstream callers via code-graph-analyzer's GraphQueryClient.find_callers(), TestSelector picks pytest nodeids whose imports overlap impacted symbols, PytestImpactPlugin injects --select-impacted-only flag. Cross-service mode consumes multi-repo-orchestrator's service-graph.json to select cross-service e2e tests on fleet changes. Activate when the user says "test impact analysis", "test selection", "only run affected tests", "diff-aware tests", "TIA".
---

# Test Impact Analysis — OOP

**Closes the flagship loop: consumes `code-graph-analyzer` + `multi-repo-orchestrator` to select only tests touching changed code.** Go from 2h full-suite runs to 5min targeted runs on typical PRs.

## Classes

```python
# tests/framework/tia/diff_loader.py
import subprocess
from pathlib import Path


class GitDiffLoader:
    def changed_files(self, *, base: str = "origin/main", head: str = "HEAD") -> list[Path]:
        r = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"],
                           capture_output=True, text=True, check=True)
        return [Path(ln) for ln in r.stdout.splitlines() if ln.endswith(".py")]
```

```python
# tests/framework/tia/resolver.py
from pathlib import Path

import allure

from tests.framework.codegraph.graph_query_client import GraphQueryClient


class ImpactedSymbolResolver:
    def __init__(self, graph: GraphQueryClient) -> None:
        self.graph = graph

    @allure.step("Resolve symbols impacted by {changed_files}")
    def resolve(self, changed_files: list[Path]) -> set[str]:
        impacted: set[str] = set()
        for f in changed_files:
            module = str(f).replace("/", ".").replace(".py", "")
            for sym in self.graph.symbols_in_file(module):
                impacted.add(sym)
                # Walk callers transitively (up to 3 hops)
                frontier = {sym}
                for _ in range(3):
                    callers = {c.qualified_name for s in frontier
                               for c in self.graph.find_callers(s)}
                    impacted |= callers
                    frontier = callers - impacted
        return impacted
```

```python
# tests/framework/tia/selector.py
import ast
from pathlib import Path

import allure


class TestSelector:
    def __init__(self, tests_root: str | Path = "tests") -> None:
        self.tests_root = Path(tests_root)

    @allure.step("Select tests touching {impacted} symbols")
    def select(self, impacted_symbols: set[str]) -> list[str]:
        selected: list[str] = []
        for test_file in self.tests_root.rglob("test_*.py"):
            imports = self._imports(test_file)
            if imports & impacted_symbols:
                selected.append(str(test_file))
        return selected

    def _imports(self, path: Path) -> set[str]:
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            return set()
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    out.add(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    out.add(alias.name)
        return out
```

```python
# tests/framework/tia/pytest_plugin.py
import pytest

from tests.framework.codegraph.graph_query_client import GraphQueryClient

from .diff_loader import GitDiffLoader
from .resolver import ImpactedSymbolResolver
from .selector import TestSelector


def pytest_addoption(parser):
    parser.addoption("--select-impacted-only", action="store_true",
                     help="run only tests impacted by git diff vs origin/main")
    parser.addoption("--impact-base", default="origin/main")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--select-impacted-only"):
        return
    changed = GitDiffLoader().changed_files(base=config.getoption("--impact-base"))
    if not changed:
        return
    graph = GraphQueryClient.from_index("artifacts/code-graph")
    impacted = ImpactedSymbolResolver(graph).resolve(changed)
    keep_paths = set(TestSelector().select(impacted))
    deselected = [it for it in items if str(it.fspath) not in keep_paths]
    items[:] = [it for it in items if str(it.fspath) in keep_paths]
    config.hook.pytest_deselected(items=deselected)
```

## Cross-service mode

```python
# tests/framework/tia/cross_service.py
import json
from pathlib import Path


class CrossServiceSelector:
    def __init__(self, service_graph_path: str = "artifacts/service-graph.json"):
        self.graph = json.loads(Path(service_graph_path).read_text())

    def affected_services(self, changed_service: str) -> set[str]:
        affected = {changed_service}
        frontier = {changed_service}
        while frontier:
            nxt = {e["source"] for e in self.graph["edges"] if e["target"] in frontier}
            nxt -= affected
            affected |= nxt
            frontier = nxt
        return affected
```

## Example

```
# PR changes src/billing/refund.py → run only affected tests
pytest --select-impacted-only --impact-base=origin/main
```

Typical result: 142 tests → 8 tests, 2h → 4 min. Full suite runs nightly regardless.

## Common Pitfalls

- Must re-index the code graph before TIA; stale graph = stale selection.
- Configuration / fixture / conftest.py changes invalidate broader scope — always run full suite if those change.
- 3-hop caller traversal is usually enough; deeper risks selecting the whole suite.
- Integration / e2e tests often don't share imports with SUT — tag them with custom marker, always run on relevant service changes.

## Related Skills

- `code-graph-analyzer` — provides the `GraphQueryClient.find_callers` that powers resolution.
- `multi-repo-orchestrator` — `service-graph.json` drives cross-service selection.
- `flaky-test-detector` — rerun flaky-quarantined tests separately even if not impacted.
- `ci-cd-templates` — wire `--select-impacted-only` into PR pipeline, full suite into nightly.
