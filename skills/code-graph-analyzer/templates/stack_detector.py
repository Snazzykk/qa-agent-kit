"""StackDetector — scans the SUT and emits a DetectedStack that every arch-*
skill consumes to decide which chain to invoke."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Self

import allure

from tests.framework.codegraph.dataclasses import DetectedStack


class StackDetector:
    """Inspects manifests + imports to determine what the SUT actually uses.

    Signals (in precedence order):
      1. pyproject.toml [project].dependencies / [tool.poetry].dependencies
      2. requirements*.txt
      3. `import` / `from ... import` across first-party source
      4. package.json (for frontend detection)
    """

    _BACKEND = {
        "fastapi": "fastapi",
        "flask": "flask",
        "django": "django",
        "starlette": "starlette",
        "aiohttp": "aiohttp",
        "sanic": "sanic",
    }
    _ORM = {
        "sqlalchemy": "sqlalchemy",
        "django.db": "django-orm",
        "tortoise": "tortoise",
        "peewee": "peewee",
    }
    _MESSAGING = {
        "kafka": "kafka-python",
        "aiokafka": "aiokafka",
        "confluent_kafka": "confluent-kafka",
        "pika": "pika",
        "aio_pika": "aio-pika",
        "celery": "celery",
    }
    _STREAMS = {
        "websockets": "websockets",
        "fastapi.websockets": "fastapi-websocket",
        "sse_starlette": "sse-starlette",
    }
    _HTTP = {
        "httpx": "httpx",
        "requests": "requests",
        "aiohttp.client": "aiohttp",
    }
    _ANALYTICS = {
        "clickhouse_driver": "clickhouse-driver",
        "clickhouse_connect": "clickhouse-connect",
    }
    _RPC = {
        "grpc": "grpcio",
        "graphene": "graphene",
        "strawberry": "strawberry",
        "sgqlc": "sgqlc",
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------------ detect
    @allure.step("StackDetector.detect")
    def detect(self) -> DetectedStack:
        imports = self._collect_imports()
        deps = self._collect_declared_deps()
        corpus = imports | deps

        backend = tuple(sorted({v for k, v in self._BACKEND.items() if k in corpus}))
        orm = tuple(sorted({v for k, v in self._ORM.items() if k in corpus}))
        messaging = tuple(sorted({v for k, v in self._MESSAGING.items() if k in corpus}))
        streams = tuple(sorted({v for k, v in self._STREAMS.items() if k in corpus}))
        http_clients = tuple(sorted({v for k, v in self._HTTP.items() if k in corpus}))
        analytics = tuple(sorted({v for k, v in self._ANALYTICS.items() if k in corpus}))
        rpc = tuple(sorted({v for k, v in self._RPC.items() if k in corpus}))

        return DetectedStack(
            backend=backend,
            orm=orm,
            pydantic=self._detect_pydantic_version(),
            messaging=messaging,
            streams=streams,
            http_clients=http_clients,
            analytics=analytics,
            rpc=rpc,
            async_runtime=self._detect_async_runtime(corpus),
            frontend=self._detect_frontend(),
        )

    # ---------------------------------------------------------- recommend
    @allure.step("StackDetector.recommend_chain")
    def recommend_chain(self, stack: DetectedStack) -> list[str]:
        """Map DetectedStack → ordered list of skill names."""
        chain: list[str] = ["source-code-audit"]

        if stack.rpc and ("grpcio" in stack.rpc):
            chain.append("arch-service-object-grpc")
        if stack.rpc and any(v in stack.rpc for v in ("graphene", "strawberry", "sgqlc")):
            chain.append("arch-service-object-graphql")
        if stack.backend:
            chain.append("arch-service-object-rest")

        if stack.messaging:
            chain.append("arch-kafka-testing")
        if stack.analytics:
            chain.append("arch-clickhouse-testing")

        if stack.frontend:
            chain.extend(["arch-playwright-pom", "arch-page-components"])

        chain.append("source-aware-test-gen")
        return chain

    # ----------------------------------------------------------------- helpers
    def _collect_imports(self) -> set[str]:
        pattern = re.compile(r"^\s*(?:from\s+([\w\.]+)|import\s+([\w\.]+))", re.M)
        found: set[str] = set()
        for file in self.root.rglob("*.py"):
            if any(part in {".venv", "venv", ".tox", "node_modules"} for part in file.parts):
                continue
            try:
                text = file.read_text(errors="ignore")
            except OSError:
                continue
            for m in pattern.finditer(text):
                mod = m.group(1) or m.group(2)
                if mod:
                    found.add(mod.split(".")[0])
                    found.add(mod)
        return found

    def _collect_declared_deps(self) -> set[str]:
        deps: set[str] = set()
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                project = data.get("project", {})
                for d in project.get("dependencies", []):
                    deps.add(self._canon_dep(d))
                poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                for name in poetry:
                    deps.add(self._canon_dep(name))
            except Exception:
                pass
        for req in self.root.glob("requirements*.txt"):
            for line in req.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.add(self._canon_dep(line))
        return deps

    @staticmethod
    def _canon_dep(spec: str) -> str:
        return re.split(r"[<>=!\[;\s]", spec, 1)[0].replace("-", "_")

    def _detect_pydantic_version(self) -> str:
        pyproject = self.root / "pyproject.toml"
        for requirement_file in [pyproject, *self.root.glob("requirements*.txt")]:
            if not requirement_file.exists():
                continue
            text = requirement_file.read_text(errors="ignore")
            if "pydantic" not in text:
                continue
            if re.search(r"pydantic\s*[=~><]+\s*2", text):
                return "v2"
            if re.search(r"pydantic\s*[=~><]+\s*1", text):
                return "v1"
        if any(self.root.rglob("*.py")):
            for file in self.root.rglob("*.py"):
                try:
                    txt = file.read_text(errors="ignore")
                except OSError:
                    continue
                if "from pydantic import" in txt or "import pydantic" in txt:
                    return "v2"
        return "none"

    @staticmethod
    def _detect_async_runtime(corpus: set[str]) -> tuple[str, ...]:
        found: list[str] = []
        if "asyncio" in corpus:
            found.append("asyncio")
        if "trio" in corpus:
            found.append("trio")
        if "anyio" in corpus:
            found.append("anyio")
        return tuple(found)

    def _detect_frontend(self) -> tuple[str, ...]:
        pkg = self.root / "package.json"
        if not pkg.exists():
            for nested in self.root.rglob("package.json"):
                if any(part in {"node_modules", ".next"} for part in nested.parts):
                    continue
                pkg = nested
                break
        if not pkg.exists():
            return ()
        text = pkg.read_text(errors="ignore")
        found: list[str] = []
        if '"next"' in text:
            found.append("next.js")
        if '"react"' in text:
            found.append("react")
        if '"vue"' in text:
            found.append("vue")
        if '"@angular/core"' in text:
            found.append("angular")
        return tuple(found)
