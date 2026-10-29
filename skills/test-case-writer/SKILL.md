---
name: test-case-writer
description: OOP test case generator — ACSource loads AC from paste/file/Jira/Linear, EdgeCaseGenerator expands each AC (positive/negative/boundary/security), TestCase dataclass, TestCaseBuilder fluent, PriorityAssigner (P0/P1/P2), Exporter (Markdown table / Gherkin / Xray JSON). Activate when the user says "test cases from ac", "gherkin scenarios", "test scenarios".
---

# Test Case Writer — OOP

Strict OOP pipeline: **`ACSource` → `EdgeCaseGenerator` → `TestCaseBuilder` → `PriorityAssigner` → `Exporter`.** Every scenario is a typed `TestCase`; formatters swap without touching generation logic.

## When to Activate

- User says "test cases from ac", "gherkin scenarios", "test scenarios".
- User pastes AC bullets or links a Jira/Linear issue.
- After `test-plan-generator` fleshes out scope and you need the case list.
- Before `user-story-to-playwright-test` if the AC are not in Given/When/Then yet.

## Dataclasses

```python
# tests/framework/cases/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    SECURITY = "security"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


@dataclass(slots=True, frozen=True)
class AcceptanceCriterion:
    id: str                       # AC-1
    text: str
    source: str = "paste"         # paste / file / jira / linear


@dataclass(slots=True, frozen=True)
class TestCase:
    id: str                       # TC-001
    scenario: str
    kind: Kind
    priority: Priority
    severity: str                 # Blocker / Critical / Major / Minor
    steps: tuple[str, ...]
    expected: str
    ac_id: str
```

## ACSource (ABC + concretes)

```python
# tests/framework/cases/ac_sources.py
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from pathlib import Path

import allure

from .models import AcceptanceCriterion


class ACSource(ABC):
    @abstractmethod
    def load(self) -> list[AcceptanceCriterion]: ...


class PasteSource(ACSource):
    _BULLET_RE = re.compile(r"^[\*\-]\s+(?P<text>.+)$", re.M)

    def __init__(self, text: str) -> None:
        self.text = text

    @allure.step("Load AC from paste")
    def load(self) -> list[AcceptanceCriterion]:
        return [AcceptanceCriterion(id=f"AC-{i}", text=m.group("text").strip(), source="paste")
                for i, m in enumerate(self._BULLET_RE.finditer(self.text), 1)]


class FileSource(PasteSource):
    def __init__(self, path: str | Path) -> None:
        super().__init__(Path(path).read_text())

    @allure.step("Load AC from file")
    def load(self) -> list[AcceptanceCriterion]:
        return [AcceptanceCriterion(id=ac.id, text=ac.text, source="file")
                for ac in super().load()]


class JiraSource(ACSource):
    """Adapter over jira-workflow's ACParser."""
    def __init__(self, issue_key: str) -> None:
        self.issue_key = issue_key

    @allure.step("Load AC from Jira {self.issue_key}")
    def load(self) -> list[AcceptanceCriterion]:
        from tests.framework.integrations.jira.jira_client import JiraClient
        from tests.framework.integrations.jira.ac_parser import ACParser
        issue = JiraClient().fetch(self.issue_key)
        return [AcceptanceCriterion(id=ac.id, text=ac.text, source="jira")
                for ac in ACParser().parse(issue)]


class LinearSource(ACSource):
    def __init__(self, issue_id: str) -> None:
        self.issue_id = issue_id

    @allure.step("Load AC from Linear {self.issue_id}")
    def load(self) -> list[AcceptanceCriterion]:
        from tests.framework.integrations.linear.linear_client import LinearClient
        from tests.framework.integrations.linear.ac_parser import ACParser
        issue = LinearClient().fetch(self.issue_id)
        return [AcceptanceCriterion(id=ac.id, text=ac.text, source="linear")
                for ac in ACParser().parse(issue)]
```

## EdgeCaseGenerator + PriorityAssigner

```python
# tests/framework/cases/generators.py
from __future__ import annotations

import allure

from .models import AcceptanceCriterion, Kind, Priority, TestCase


class PriorityAssigner:
    """P0 = revenue / data-loss, P1 = core flow, P2 = polish."""

    _P0 = ("payment", "checkout", "auth", "login", "billing", "refund", "data loss")
    _P1 = ("search", "profile", "settings", "notification", "dashboard")

    def assign(self, ac: AcceptanceCriterion) -> Priority:
        text = ac.text.lower()
        if any(k in text for k in self._P0): return Priority.P0
        if any(k in text for k in self._P1): return Priority.P1
        return Priority.P2


class EdgeCaseGenerator:
    """Yield 4 variants per AC: positive, negative, boundary, security."""

    def __init__(self, priority: PriorityAssigner | None = None) -> None:
        self._priority = priority or PriorityAssigner()
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"TC-{self._counter:03d}"

    @allure.step("Expand {ac.id} into edge cases")
    def expand(self, ac: AcceptanceCriterion) -> list[TestCase]:
        p = self._priority.assign(ac)
        sev = {Priority.P0: "Blocker", Priority.P1: "Critical", Priority.P2: "Minor"}[p]
        return [
            TestCase(id=self._next_id(), scenario=f"{ac.text} — happy path",
                     kind=Kind.POSITIVE, priority=p, severity=sev,
                     steps=("Provide valid input", "Submit"),
                     expected="Operation succeeds", ac_id=ac.id),
            TestCase(id=self._next_id(), scenario=f"{ac.text} — invalid input rejected",
                     kind=Kind.NEGATIVE, priority=p, severity=sev,
                     steps=("Provide invalid input", "Submit"),
                     expected="{{ ask PM: exact error copy }}", ac_id=ac.id),
            TestCase(id=self._next_id(), scenario=f"{ac.text} — boundary values",
                     kind=Kind.BOUNDARY, priority=p, severity="Major",
                     steps=("Use min/max length values", "Submit"),
                     expected="Accepted or rejected per spec", ac_id=ac.id),
            TestCase(id=self._next_id(), scenario=f"{ac.text} — injection / XSS probe",
                     kind=Kind.SECURITY, priority=Priority.P0, severity="Critical",
                     steps=("Send payload `<script>alert(1)</script>`", "Submit"),
                     expected="Payload escaped; no script executes", ac_id=ac.id),
        ]
```

## TestCaseBuilder (fluent)

```python
# tests/framework/cases/test_case_builder.py
from __future__ import annotations
from typing import Self

import allure

from .ac_sources import ACSource
from .generators import EdgeCaseGenerator
from .models import TestCase


class TestCaseBuilder:
    def __init__(self, generator: EdgeCaseGenerator | None = None) -> None:
        self._source: ACSource | None = None
        self._generator = generator or EdgeCaseGenerator()
        self._extra: list[TestCase] = []

    def from_source(self, source: ACSource) -> Self:
        self._source = source
        return self

    def with_case(self, case: TestCase) -> Self:
        self._extra.append(case)
        return self

    @allure.step("Build test cases")
    def build(self) -> list[TestCase]:
        if self._source is None:
            return list(self._extra)
        out: list[TestCase] = []
        for ac in self._source.load():
            out.extend(self._generator.expand(ac))
        out.extend(self._extra)
        return out
```

## Exporters

```python
# tests/framework/cases/exporters.py
from __future__ import annotations
import json
from abc import ABC, abstractmethod
from pathlib import Path

import allure

from .models import TestCase


class Exporter(ABC):
    @abstractmethod
    def export(self, cases: list[TestCase], out: str | Path) -> Path: ...


class MarkdownTableExporter(Exporter):
    @allure.step("Export Markdown table → {out}")
    def export(self, cases, out):
        lines = ["| ID | Scenario | Kind | Priority | Severity | Expected |",
                 "|---|---|---|---|---|---|"]
        lines += [f"| {c.id} | {c.scenario} | {c.kind.value} | {c.priority.value} | {c.severity} | {c.expected} |"
                  for c in cases]
        Path(out).write_text("\n".join(lines))
        return Path(out)


class GherkinExporter(Exporter):
    @allure.step("Export Gherkin → {out}")
    def export(self, cases, out):
        lines: list[str] = []
        for c in cases:
            lines += [f"Scenario: {c.scenario}"]
            lines += [f"  Given {c.steps[0]}"] if c.steps else []
            lines += [f"  When {s}" for s in c.steps[1:]]
            lines += [f"  Then {c.expected}", ""]
        Path(out).write_text("\n".join(lines))
        return Path(out)


class XrayJsonExporter(Exporter):
    @allure.step("Export Xray JSON → {out}")
    def export(self, cases, out):
        payload = [{"summary": c.scenario, "type": "Manual",
                    "priority": c.priority.value, "severity": c.severity,
                    "steps": [{"action": s, "result": c.expected} for s in c.steps],
                    "labels": [c.kind.value, c.ac_id]} for c in cases]
        Path(out).write_text(json.dumps(payload, indent=2))
        return Path(out)
```

## Example — 3 AC bullets → 12-row table

```python
from tests.framework.cases.ac_sources import PasteSource
from tests.framework.cases.exporters import MarkdownTableExporter
from tests.framework.cases.test_case_builder import TestCaseBuilder

ac_text = """
- User can log in with valid email + password
- User sees an error when password is wrong
- User can reset password via email link
"""

cases = TestCaseBuilder().from_source(PasteSource(ac_text)).build()
MarkdownTableExporter().export(cases, "test_cases.md")   # 12 rows (3 AC × 4 variants)
```

## Common Pitfalls

- Never invent exact error copy — emit `{{ ask PM: ... }}` placeholders for the team to fill.
- `SECURITY` variants always bump to P0 even if core AC is P2.
- Don't skip BOUNDARY just because AC looks simple — off-by-one bugs live there.
- Export once per target tool; don't pipe Xray JSON into a wiki page.

## Related Skills

- `test-plan-generator` — upstream scope source.
- `user-story-to-playwright-test` — auto-implement P0/P1 cases in Playwright.
- `api-test-generator` — auto-implement API-layer cases.
- `jira-workflow` / `linear-workflow` — posts the table back to the tracker.
