"""High-level query API. The ONLY surface downstream skills should touch."""
from __future__ import annotations

from pathlib import Path
from typing import Self

import allure

from tests.framework.codegraph.dataclasses import (
    FunctionRef,
    ORMEntityRef,
    PydanticModelRef,
    RequestResponseShape,
    RouteInfo,
)
from tests.framework.codegraph.graph_provider import GraphProvider


class GraphQueryClient:
    """Backend-agnostic query facade.

    Consumers (source-code-audit, source-aware-test-gen, arch-*) should always
    construct a GraphQueryClient(provider) and call the typed methods below.
    Never call provider.cypher(...) directly from a skill — it makes the
    skill brittle across providers.
    """

    def __init__(self, provider: GraphProvider) -> None:
        self._provider = provider

    # ------------------------------------------------------------------ routes
    @allure.step("Graph.find_routes")
    def find_routes(self) -> list[RouteInfo]:
        rows = self._provider.query("routes")
        return [self._to_route(r) for r in rows]

    @allure.step("Graph.find_handlers_for_route({path})")
    def find_handlers_for_route(self, path: str) -> list[FunctionRef]:
        rows = self._provider.query("handlers_for_route", path=path)
        return [self._to_function(r) for r in rows]

    # ------------------------------------------------------------------ models
    @allure.step("Graph.find_models")
    def find_models(self) -> list[PydanticModelRef]:
        rows = self._provider.query("pydantic_models")
        return [self._to_model(r) for r in rows]

    @allure.step("Graph.find_orm_entities")
    def find_orm_entities(self) -> list[ORMEntityRef]:
        rows = self._provider.query("orm_entities")
        return [self._to_orm(r) for r in rows]

    # --------------------------------------------------------- call graph nav
    @allure.step("Graph.find_callers({symbol})")
    def find_callers(self, symbol: str) -> list[FunctionRef]:
        rows = self._provider.query("callers", symbol=symbol)
        return [self._to_function(r) for r in rows]

    @allure.step("Graph.find_callees({symbol})")
    def find_callees(self, symbol: str) -> list[FunctionRef]:
        rows = self._provider.query("callees", symbol=symbol)
        return [self._to_function(r) for r in rows]

    # ------------------------------------------------------------ source slice
    @allure.step("Graph.get_function_source({symbol})")
    def get_function_source(self, symbol: str) -> str:
        rows = self._provider.query("function_source", symbol=symbol)
        if not rows:
            raise KeyError(f"function not in graph: {symbol}")
        row = rows[0]
        source = row.get("source")
        if source is not None:
            return str(source)
        # Fallback: slice the file by lineno/end_lineno from the graph.
        file = Path(row["file"])
        start, end = int(row["lineno"]), int(row["end_lineno"])
        lines = file.read_text().splitlines()
        return "\n".join(lines[start - 1:end])

    @allure.step("Graph.get_class_source({symbol})")
    def get_class_source(self, symbol: str) -> str:
        rows = self._provider.query("class_source", symbol=symbol)
        if not rows:
            raise KeyError(f"class not in graph: {symbol}")
        row = rows[0]
        source = row.get("source")
        if source is not None:
            return str(source)
        file = Path(row["file"])
        start, end = int(row["lineno"]), int(row["end_lineno"])
        lines = file.read_text().splitlines()
        return "\n".join(lines[start - 1:end])

    # ----------------------------------------------------- request/response
    @allure.step("Graph.shape_of({endpoint})")
    def shape_of(self, endpoint: str) -> RequestResponseShape:
        rows = self._provider.query("shape_of", endpoint=endpoint)
        if not rows:
            raise KeyError(f"endpoint not in graph: {endpoint}")
        return self._to_shape(rows[0])

    # ------------------------------------------------------------ converters
    @staticmethod
    def _to_function(row: dict) -> FunctionRef:
        return FunctionRef(
            qualified_name=row["qualified_name"],
            file=Path(row["file"]),
            lineno=int(row["lineno"]),
            end_lineno=int(row.get("end_lineno", row["lineno"])),
            is_async=bool(row.get("is_async", False)),
            is_method=bool(row.get("is_method", False)),
            decorators=tuple(row.get("decorators", ())),
        )

    @staticmethod
    def _to_model(row: dict) -> PydanticModelRef:
        return PydanticModelRef(
            qualified_name=row["qualified_name"],
            file=Path(row["file"]),
            lineno=int(row["lineno"]),
            pydantic_version=row.get("pydantic_version", "v2"),
            fields=tuple((f["name"], f["annotation"]) for f in row.get("fields", [])),
            is_input=bool(row.get("is_input", False)),
            is_output=bool(row.get("is_output", False)),
        )

    @staticmethod
    def _to_orm(row: dict) -> ORMEntityRef:
        return ORMEntityRef(
            qualified_name=row["qualified_name"],
            file=Path(row["file"]),
            table_name=row.get("table_name", ""),
            orm=row.get("orm", "sqlalchemy"),
            fields=tuple((f["name"], f["type"]) for f in row.get("fields", [])),
            relations=tuple((r["name"], r["target"]) for r in row.get("relations", [])),
        )

    def _to_route(self, row: dict) -> RouteInfo:
        return RouteInfo(
            method=row["method"].upper(),
            path=row["path"],
            handler=self._to_function(row["handler"]),
            framework=row.get("framework", "fastapi"),
            request_model=row.get("request_model"),
            response_model=row.get("response_model"),
            status_codes=tuple(row.get("status_codes", (200,))),
            auth=row.get("auth", "public"),
        )

    def _to_shape(self, row: dict) -> RequestResponseShape:
        return RequestResponseShape(
            route=self._to_route(row["route"]),
            request_example=row.get("request_example"),
            response_example=row.get("response_example"),
            error_examples=tuple(row.get("error_examples", ())),
        )
