---
name: pytest-failure-analyzer
description: OOP pytest failure analyzer — FailureParser reads junit.xml / text / allure-results, FailurePattern registry classifies each, FailureAnalyzer groups by root cause, FailureReport emits markdown with rerun commands. Activate when the user says "why did my tests fail", "pytest failure analysis", "debug failing test", or pastes pytest output.
---

# Pytest Failure Analyzer — OOP

Strict OOP pipeline: **`FailureParser` → `FailurePattern` registry → `FailureAnalyzer` → `FailureReport`.** No ad-hoc regex scripts, no procedural one-offs.

## When to Activate

- User pastes a pytest traceback or `=== FAILURES ===` block.
- User says "why did my tests fail", "pytest failure analysis", "debug failing test".
- CI job failed and the user wants root-cause grouping before retrying.
- Before `flaky-test-detector` (this classifies one run; that classifies many).

## FailureEntry

```python
# tests/framework/analysis/failure_entry.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(slots=True)
class FailureEntry:
    nodeid: str                 # e.g. tests/api/test_users.py::TestCreate::test_201
    message: str                # short error headline
    traceback: str              # full traceback text
    duration_s: float = 0.0
    stdout: str = ""
    stderr: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class Fix:
    summary: str                # one-line actionable fix
    diff: str | None = None     # optional unified diff
    rerun: str | None = None    # rerun command
```

## FailureParser (3 inputs, one API)

```python
# tests/framework/analysis/failure_parser.py
from __future__ import annotations
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import allure

from .failure_entry import FailureEntry


class FailureParser:
    """Reads pytest output in any supported format and yields FailureEntry list."""

    _FAILURES_RE = re.compile(r"_{5,}\s+(?P<nodeid>\S+)\s+_{5,}\n(?P<body>.*?)(?=\n_{5,}|\Z)", re.S)

    @allure.step("Parse pytest text output")
    def parse_text(self, text: str) -> list[FailureEntry]:
        entries: list[FailureEntry] = []
        for m in self._FAILURES_RE.finditer(text):
            body = m.group("body")
            headline = next((ln for ln in body.splitlines() if ln.startswith("E ")), "").lstrip("E ").strip()
            entries.append(FailureEntry(nodeid=m.group("nodeid"), message=headline, traceback=body))
        return entries

    @allure.step("Parse junit.xml from {path}")
    def parse_junit(self, path: str | Path) -> list[FailureEntry]:
        root = ET.parse(path).getroot()
        out: list[FailureEntry] = []
        for case in root.iter("testcase"):
            failure = case.find("failure") or case.find("error")
            if failure is None:
                continue
            out.append(FailureEntry(
                nodeid=f"{case.get('classname')}::{case.get('name')}",
                message=failure.get("message", ""),
                traceback=failure.text or "",
                duration_s=float(case.get("time", 0.0)),
            ))
        return out

    @allure.step("Parse allure-results from {path}")
    def parse_allure(self, path: str | Path) -> list[FailureEntry]:
        out: list[FailureEntry] = []
        for p in Path(path).glob("*-result.json"):
            raw = json.loads(p.read_text())
            if raw.get("status") not in {"failed", "broken"}:
                continue
            status = raw.get("statusDetails", {})
            out.append(FailureEntry(
                nodeid=raw.get("fullName", raw.get("name", p.stem)),
                message=status.get("message", ""),
                traceback=status.get("trace", ""),
            ))
        return out
```

## FailurePattern Registry (ABC + concretes)

```python
# tests/framework/analysis/failure_patterns.py
from __future__ import annotations
from abc import ABC, abstractmethod
import re

from .failure_entry import FailureEntry, Fix


class FailurePattern(ABC):
    name: str = ""
    severity: str = "medium"

    @abstractmethod
    def match(self, entry: FailureEntry) -> bool: ...

    @abstractmethod
    def suggest(self, entry: FailureEntry) -> Fix: ...


class AssertionMismatch(FailurePattern):
    name = "assertion_mismatch"
    _RE = re.compile(r"^E\s+assert|AssertionError", re.M)

    def match(self, entry): return bool(self._RE.search(entry.traceback))
    def suggest(self, entry):
        return Fix(summary="Value mismatch. Compare expected vs actual; update fixture or fix SUT.",
                   rerun=f"pytest '{entry.nodeid}' -vv")


class TimingFailure(FailurePattern):
    name = "timing"
    severity = "high"
    _RE = re.compile(r"TimeoutError|asyncio\.TimeoutError|wait_for_timeout|ElementNotVisibleException", re.I)

    def match(self, entry): return bool(self._RE.search(entry.traceback))
    def suggest(self, entry):
        return Fix(summary="Race condition or slow backend. Replace sleeps with `expect(...)` / poll.",
                   rerun=f"pytest '{entry.nodeid}' --reruns 2")


class FixtureConfig(FailurePattern):
    name = "fixture_config"
    _RE = re.compile(r"fixture '[^']+' not found|ScopeMismatch|FixtureLookupError")

    def match(self, entry): return bool(self._RE.search(entry.traceback))
    def suggest(self, entry):
        return Fix(summary="Fixture wiring broken. Check conftest.py location / scope / name.",
                   rerun=f"pytest '{entry.nodeid}' --setup-show")


class DataCollision(FailurePattern):
    name = "data_collision"
    _RE = re.compile(r"IntegrityError|UniqueViolation|duplicate key|already exists", re.I)

    def match(self, entry): return bool(self._RE.search(entry.traceback))
    def suggest(self, entry):
        return Fix(summary="Shared test data collides. Use Faker seed per-test or transactional rollback.",
                   rerun=f"pytest '{entry.nodeid}' -p no:cacheprovider")


class EnvUnreachable(FailurePattern):
    name = "env_unreachable"
    severity = "high"
    _RE = re.compile(r"ConnectionError|ConnectError|Name or service not known|refused", re.I)

    def match(self, entry): return bool(self._RE.search(entry.traceback))
    def suggest(self, entry):
        return Fix(summary="Target service down. Verify BASE_URL + docker-compose health.",
                   rerun="docker compose up -d && pytest")


class ImportError_(FailurePattern):
    name = "import_error"
    severity = "critical"
    _RE = re.compile(r"ModuleNotFoundError|ImportError|collection error", re.I)

    def match(self, entry): return bool(self._RE.search(entry.traceback))
    def suggest(self, entry):
        return Fix(summary="Missing dependency or bad PYTHONPATH. Reinstall deps / fix imports.",
                   rerun="pip install -e . && pytest --collect-only")
```

## FailureAnalyzer

```python
# tests/framework/analysis/failure_analyzer.py
from __future__ import annotations
from dataclasses import dataclass, field

import allure

from .failure_entry import FailureEntry, Fix
from .failure_patterns import (
    FailurePattern, AssertionMismatch, TimingFailure, FixtureConfig,
    DataCollision, EnvUnreachable, ImportError_,
)


@dataclass(slots=True)
class FailureGroup:
    pattern: str
    severity: str
    entries: list[FailureEntry] = field(default_factory=list)
    fix: Fix | None = None


class FailureAnalyzer:
    """Applies ordered pattern registry, groups entries by first match, ranks by severity."""

    DEFAULT_PATTERNS: tuple[type[FailurePattern], ...] = (
        ImportError_, EnvUnreachable, FixtureConfig, TimingFailure,
        DataCollision, AssertionMismatch,
    )
    _SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, patterns: list[FailurePattern] | None = None) -> None:
        self.patterns = patterns or [cls() for cls in self.DEFAULT_PATTERNS]

    @allure.step("Classify failures")
    def analyze(self, entries: list[FailureEntry]) -> list[FailureGroup]:
        buckets: dict[str, FailureGroup] = {}
        for entry in entries:
            for pattern in self.patterns:
                if pattern.match(entry):
                    grp = buckets.setdefault(
                        pattern.name,
                        FailureGroup(pattern=pattern.name, severity=pattern.severity, fix=pattern.suggest(entry)),
                    )
                    grp.entries.append(entry)
                    break
            else:
                buckets.setdefault("unclassified", FailureGroup(pattern="unclassified", severity="low")).entries.append(entry)
        return sorted(buckets.values(), key=lambda g: self._SEVERITY.get(g.severity, 9))
```

## FailureReport

```python
# tests/framework/analysis/failure_report.py
from __future__ import annotations
from pathlib import Path

import allure

from .failure_analyzer import FailureGroup


class FailureReport:
    """Renders grouped failures as markdown with per-group rerun commands."""

    @allure.step("Render markdown report to {out}")
    def render(self, groups: list[FailureGroup], out: str | Path = "failure-report.md") -> Path:
        lines = ["# Pytest Failure Report", ""]
        for grp in groups:
            lines += [f"## {grp.pattern} ({grp.severity}) — {len(grp.entries)} tests", ""]
            if grp.fix:
                lines += [f"- Fix: {grp.fix.summary}"]
                if grp.fix.rerun:
                    lines += [f"- Rerun: `{grp.fix.rerun}`"]
            lines += ["", "<details><summary>Failing tests</summary>", ""]
            lines += [f"- `{e.nodeid}` — {e.message}" for e in grp.entries]
            lines += ["", "</details>", ""]
        path = Path(out)
        path.write_text("\n".join(lines))
        return path
```

## Common Pitfalls

- Don't stop at the first regex hit — order matters (import errors before assertions).
- Text parser is best-effort; prefer `junit.xml` or `allure-results/` when available.
- Rerun commands are suggestions; never auto-execute destructive rerun flags in CI.

## Related Skills

- `flaky-test-detector` — run history (many runs) classifier, reuses `FailurePattern`.
- `allure-report-insights` — consumes `allure-results/` for digests.
- `bug-report-writer` — turn a classified group into a Jira/Linear ticket.
- `production-error-to-regression-test` — promote recurring unclassified groups to tests.
