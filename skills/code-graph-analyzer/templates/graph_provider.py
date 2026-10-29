"""GraphProvider ABC + three concrete backends.

Downstream code should never import concretes directly — always go through
GraphQueryClient which takes a GraphProvider instance.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Self

import allure

from tests.framework.codegraph.dataclasses import (
    DetectedStack,
    FunctionRef,
    ORMEntityRef,
    PydanticModelRef,
    RouteInfo,
)


class GraphProvider(ABC):
    """Backend-agnostic contract for a code knowledge graph.

    Implementations wrap either an MCP server (CodeGraphContext, gitnexus) or a
    local in-process graph (tree-sitter + networkx). All return plain dicts
    from `query` / `cypher`; higher-level dataclasses live in GraphQueryClient.
    """

    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def ensure_installed(self) -> Self: ...

    @abstractmethod
    def index(self, root: Path) -> Self: ...

    @abstractmethod
    def query(self, query: str, **params: Any) -> list[dict]: ...

    @abstractmethod
    def cypher(self, cypher: str, **params: Any) -> list[dict]: ...

    def refresh(self, root: Path, since: str = "HEAD~1") -> Self:
        """Default: full reindex. Providers with incremental support override."""
        return self.index(root)


class CodeGraphContextProvider(GraphProvider):
    """Free, neo4j-backed MCP server (CodeGraphContext).

    https://github.com/Shashankss1205/CodeGraphContext

    On first use we verify the CLI is on PATH and that neo4j is reachable.
    If either is missing, CodeGraphInstaller (see installer.py) is invoked.
    """

    name = "codegraphcontext"

    def __init__(self, bolt_url: str | None = None) -> None:
        self.bolt_url = bolt_url or os.environ.get("CGC_BOLT_URL", "bolt://localhost:7687")
        self._indexed_root: Path | None = None

    @allure.step("CodeGraphContext.is_available")
    def is_available(self) -> bool:
        return shutil.which("codegraphcontext") is not None

    @allure.step("CodeGraphContext.ensure_installed")
    def ensure_installed(self) -> Self:
        if self.is_available():
            return self
        from tests.framework.codegraph.installer import CodeGraphInstaller
        CodeGraphInstaller().ensure_installed().start_neo4j_if_needed()
        return self

    @allure.step("CodeGraphContext.index({root})")
    def index(self, root: Path) -> Self:
        self.ensure_installed()
        subprocess.run(
            ["codegraphcontext", "index", "--root", str(root), "--bolt", self.bolt_url],
            check=True,
        )
        self._indexed_root = root
        return self

    @allure.step("CodeGraphContext.refresh({root})")
    def refresh(self, root: Path, since: str = "HEAD~1") -> Self:
        self.ensure_installed()
        subprocess.run(
            ["codegraphcontext", "refresh", "--root", str(root), "--since", since],
            check=True,
        )
        return self

    @allure.step("CodeGraphContext.query")
    def query(self, query: str, **params: Any) -> list[dict]:
        proc = subprocess.run(
            ["codegraphcontext", "query", "--json", query, "--params", json.dumps(params)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout or "[]")

    @allure.step("CodeGraphContext.cypher")
    def cypher(self, cypher: str, **params: Any) -> list[dict]:
        proc = subprocess.run(
            ["codegraphcontext", "cypher", "--json", cypher, "--params", json.dumps(params)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout or "[]")


class GitNexusProvider(GraphProvider):
    """Paid gitnexus MCP.

    Wraps the mcp__gitnexus__* toolset:
      - list_repos, query, cypher, context, impact, route_map,
        shape_check, tool_map, rename, api_impact

    Because MCP tool calls happen through the harness, this class documents
    the expected contract; the actual call site is the skill loader that
    forwards to the MCP runtime. The `invoke_mcp` hook is injected by the
    harness at runtime — we keep it overridable for testing.
    """

    name = "gitnexus"

    def __init__(self, repo: str | None = None, invoke_mcp=None) -> None:
        self.repo = repo
        self._invoke_mcp = invoke_mcp  # injected by harness

    @allure.step("GitNexus.is_available")
    def is_available(self) -> bool:
        return self._invoke_mcp is not None

    @allure.step("GitNexus.ensure_installed")
    def ensure_installed(self) -> Self:
        if not self.is_available():
            raise RuntimeError(
                "gitnexus MCP is paid and must be configured in .mcp.json. "
                "Fall back to CodeGraphContextProvider for a free alternative."
            )
        return self

    @allure.step("GitNexus.index({root})")
    def index(self, root: Path) -> Self:
        # gitnexus indexes via its CLI; MCP users point `repo` at an already-indexed path.
        self.repo = str(root)
        return self

    @allure.step("GitNexus.query")
    def query(self, query: str, **params: Any) -> list[dict]:
        self.ensure_installed()
        return list(self._invoke_mcp("mcp__gitnexus__query", {"query": query, **params}))

    @allure.step("GitNexus.cypher")
    def cypher(self, cypher: str, **params: Any) -> list[dict]:
        self.ensure_installed()
        return list(self._invoke_mcp("mcp__gitnexus__cypher", {"cypher": cypher, **params}))

    @allure.step("GitNexus.route_map")
    def route_map(self) -> list[dict]:
        self.ensure_installed()
        return list(self._invoke_mcp("mcp__gitnexus__route_map", {"repo": self.repo}))

    @allure.step("GitNexus.shape_check({endpoint})")
    def shape_check(self, endpoint: str) -> dict:
        self.ensure_installed()
        return dict(self._invoke_mcp("mcp__gitnexus__shape_check", {"endpoint": endpoint}))

    @allure.step("GitNexus.impact({symbol})")
    def impact(self, symbol: str) -> list[dict]:
        self.ensure_installed()
        return list(self._invoke_mcp("mcp__gitnexus__impact", {"symbol": symbol}))


class TreeSitterProvider(GraphProvider):
    """Pure-Python fallback. tree-sitter + networkx in-process.

    Use when no MCP is available. Slower on > 10K files, but zero setup and
    enough for small to medium projects. Builds a DiGraph of:
      - function / method nodes
      - class nodes
      - import edges
      - call edges (tree-sitter query for `call_expression`)
      - decorator edges (used for FastAPI / Flask route detection)
    """

    name = "tree-sitter"

    def __init__(self) -> None:
        self._graph = None
        self._files: list[Path] = []

    @allure.step("TreeSitter.is_available")
    def is_available(self) -> bool:
        try:
            import networkx  # noqa: F401
            import tree_sitter_languages  # noqa: F401
            return True
        except ImportError:
            return False

    @allure.step("TreeSitter.ensure_installed")
    def ensure_installed(self) -> Self:
        if self.is_available():
            return self
        subprocess.run(
            ["pip", "install", "networkx>=3", "tree-sitter-languages>=1.10"],
            check=True,
        )
        return self

    @allure.step("TreeSitter.index({root})")
    def index(self, root: Path) -> Self:
        self.ensure_installed()
        import networkx as nx
        from tree_sitter_languages import get_parser

        self._graph = nx.DiGraph()
        parser = get_parser("python")
        self._files = [p for p in root.rglob("*.py") if "/.venv/" not in str(p)]

        for file in self._files:
            try:
                tree = parser.parse(file.read_bytes())
                self._collect_symbols(tree, file)
            except Exception:
                continue
        return self

    def _collect_symbols(self, tree, file: Path) -> None:
        """Walk the AST, add function/class/decorator nodes to self._graph."""
        # Implementation detail — tree-sitter queries per node kind.
        # Intentionally terse here; production impl extends to call/import edges.
        root_node = tree.root_node
        cursor = root_node.walk()
        self._graph.add_node(str(file), kind="file")
        self._walk(cursor, file)

    def _walk(self, cursor, file: Path) -> None:
        reached_root = False
        while not reached_root:
            node = cursor.node
            if node.type in ("function_definition", "class_definition"):
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    qname = f"{file.stem}.{name_node.text.decode()}"
                    self._graph.add_node(
                        qname,
                        kind=node.type,
                        file=str(file),
                        lineno=node.start_point[0] + 1,
                        end_lineno=node.end_point[0] + 1,
                    )
            if cursor.goto_first_child():
                continue
            while not cursor.goto_next_sibling():
                if not cursor.goto_parent():
                    reached_root = True
                    break

    @allure.step("TreeSitter.query")
    def query(self, query: str, **params: Any) -> list[dict]:
        if self._graph is None:
            raise RuntimeError("TreeSitterProvider.index(root) must be called first")
        kind = params.get("kind")
        return [
            {"name": n, **d}
            for n, d in self._graph.nodes(data=True)
            if (kind is None or d.get("kind") == kind)
        ]

    @allure.step("TreeSitter.cypher")
    def cypher(self, cypher: str, **params: Any) -> list[dict]:
        raise NotImplementedError(
            "TreeSitterProvider does not speak Cypher. Use query(...) or switch to "
            "CodeGraphContextProvider / GitNexusProvider."
        )
