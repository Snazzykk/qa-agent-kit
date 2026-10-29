---
name: test-plan-generator
description: OOP test plan generator — PRDParser extracts features/stories from a spec, RiskAssessor scores each area (impact × likelihood), TestLevelPlanner allocates unit/integration/e2e, TestPlanBuilder composes, TestPlanRenderer emits markdown. Activate when the user says "test plan", "qa plan", "testing strategy", or points at a PRD.
---

# Test Plan Generator — OOP

Strict OOP pipeline: **`PRDParser` → `RiskAssessor` → `TestLevelPlanner` → `TestPlanBuilder` → `TestPlan` → `TestPlanRenderer`.** No free-form plans; every artifact is a typed aggregate.

## When to Activate

- User says "test plan", "qa plan", "testing strategy".
- A PRD / feature spec / Linear project / Jira epic needs an entry+exit QA doc.
- Before `test-case-writer` (plan defines scope; cases fill it).
- After `source-code-audit` when the audit suggests risk hotspots.

## Dataclasses

```python
# tests/framework/planning/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class TestLevel(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    NON_FUNCTIONAL = "non-functional"


@dataclass(slots=True, frozen=True)
class Feature:
    id: str                       # F-1, F-2
    title: str
    description: str
    stories: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class Risk:
    feature_id: str
    impact: int                   # 1..5
    likelihood: int               # 1..5

    @property
    def total(self) -> int:
        return self.impact * self.likelihood

    @property
    def bucket(self) -> str:
        if self.total >= 16: return "critical"
        if self.total >= 9:  return "high"
        if self.total >= 4:  return "medium"
        return "low"


@dataclass(slots=True, frozen=True)
class TestPlan:
    scope: tuple[Feature, ...]
    risks: tuple[Risk, ...]
    levels: dict[str, tuple[TestLevel, ...]]        # feature_id -> levels
    entry_criteria: tuple[str, ...]
    exit_criteria: tuple[str, ...]
    timeline_weeks: int
```

## PRDParser

```python
# tests/framework/planning/prd_parser.py
from __future__ import annotations
import re
from pathlib import Path

import allure

from .models import Feature


class PRDParser:
    """Parse a text/markdown PRD into Feature objects. H2/H3 headings → feature boundaries."""

    _HEADING_RE = re.compile(r"^##\s+(?P<title>.+)$", re.M)
    _STORY_RE = re.compile(r"^(?:\*|-)\s+As an? (?P<body>.+)$", re.M)

    @allure.step("Parse PRD {path}")
    def parse(self, path: str | Path) -> list[Feature]:
        text = Path(path).read_text()
        out: list[Feature] = []
        for idx, m in enumerate(self._HEADING_RE.finditer(text), 1):
            start = m.end()
            next_m = self._HEADING_RE.search(text, start)
            body = text[start:next_m.start() if next_m else len(text)]
            stories = tuple(s.group("body").strip() for s in self._STORY_RE.finditer(body))
            out.append(Feature(id=f"F-{idx}", title=m.group("title").strip(),
                               description=body.strip(), stories=stories))
        return out
```

## RiskAssessor

```python
# tests/framework/planning/risk_assessor.py
from __future__ import annotations

import allure

from .models import Feature, Risk


class RiskAssessor:
    """Heuristic 1..5 scoring. Override for domain-specific weightings."""

    _IMPACT_KEYWORDS = {"payment": 5, "auth": 5, "security": 5, "billing": 5,
                        "checkout": 4, "data": 4, "user": 3, "settings": 2, "ui": 2}
    _LIKELIHOOD_KEYWORDS = {"new": 4, "refactor": 4, "migration": 5,
                            "experiment": 3, "stable": 1, "legacy": 3}

    def impact_score(self, feature: Feature) -> int:
        text = (feature.title + " " + feature.description).lower()
        return max((v for k, v in self._IMPACT_KEYWORDS.items() if k in text), default=3)

    def likelihood_score(self, feature: Feature) -> int:
        text = (feature.title + " " + feature.description).lower()
        return max((v for k, v in self._LIKELIHOOD_KEYWORDS.items() if k in text), default=3)

    @allure.step("Assess risk for {feature.id}")
    def total(self, feature: Feature) -> Risk:
        return Risk(feature_id=feature.id,
                    impact=self.impact_score(feature),
                    likelihood=self.likelihood_score(feature))
```

## TestLevelPlanner

```python
# tests/framework/planning/test_level_planner.py
from __future__ import annotations

import allure

from .models import Risk, TestLevel


class TestLevelPlanner:
    """Assign pyramid levels based on risk bucket. High risk → all 4 levels."""

    _MATRIX: dict[str, tuple[TestLevel, ...]] = {
        "critical": (TestLevel.UNIT, TestLevel.INTEGRATION, TestLevel.E2E, TestLevel.NON_FUNCTIONAL),
        "high":     (TestLevel.UNIT, TestLevel.INTEGRATION, TestLevel.E2E),
        "medium":   (TestLevel.UNIT, TestLevel.INTEGRATION),
        "low":      (TestLevel.UNIT,),
    }

    @allure.step("Plan levels for {risk.feature_id} ({risk.bucket})")
    def plan(self, risk: Risk) -> tuple[TestLevel, ...]:
        return self._MATRIX[risk.bucket]
```

## TestPlanBuilder (fluent)

```python
# tests/framework/planning/test_plan_builder.py
from __future__ import annotations
from pathlib import Path
from typing import Self

import allure

from .models import Feature, Risk, TestLevel, TestPlan
from .prd_parser import PRDParser
from .risk_assessor import RiskAssessor
from .test_level_planner import TestLevelPlanner


class TestPlanBuilder:
    _DEFAULT_ENTRY = (
        "PRD signed off by PM/design",
        "Code freeze on target branch",
        "Test env deployed & smoke-green",
    )
    _DEFAULT_EXIT = (
        "All P0 cases pass",
        ">= 80% line coverage on changed modules",
        "Zero open Blocker / Critical bugs",
    )

    def __init__(self,
                 parser: PRDParser | None = None,
                 assessor: RiskAssessor | None = None,
                 planner: TestLevelPlanner | None = None) -> None:
        self._parser = parser or PRDParser()
        self._assessor = assessor or RiskAssessor()
        self._planner = planner or TestLevelPlanner()
        self._features: list[Feature] = []
        self._timeline_weeks = 2
        self._entry: tuple[str, ...] = self._DEFAULT_ENTRY
        self._exit: tuple[str, ...] = self._DEFAULT_EXIT

    @allure.step("Load PRD {path}")
    def from_prd(self, path: str | Path) -> Self:
        self._features = self._parser.parse(path)
        return self

    def with_timeline(self, weeks: int) -> Self:
        self._timeline_weeks = weeks
        return self

    def with_entry_criteria(self, criteria: list[str]) -> Self:
        self._entry = tuple(criteria)
        return self

    def with_exit_criteria(self, criteria: list[str]) -> Self:
        self._exit = tuple(criteria)
        return self

    @allure.step("Build TestPlan")
    def build(self) -> TestPlan:
        risks = [self._assessor.total(f) for f in self._features]
        levels: dict[str, tuple[TestLevel, ...]] = {
            r.feature_id: self._planner.plan(r) for r in risks
        }
        return TestPlan(
            scope=tuple(self._features),
            risks=tuple(risks),
            levels=levels,
            entry_criteria=self._entry,
            exit_criteria=self._exit,
            timeline_weeks=self._timeline_weeks,
        )
```

## TestPlanRenderer

```python
# tests/framework/planning/test_plan_renderer.py
from __future__ import annotations
from pathlib import Path

import allure

from .models import TestPlan


class TestPlanRenderer:
    @allure.step("Render test plan → markdown")
    def render_markdown(self, plan: TestPlan, out: str | Path = "TEST_PLAN.md") -> Path:
        lines = ["# Test Plan", "",
                 f"Timeline: **{plan.timeline_weeks} weeks**", "",
                 "## Scope", "| ID | Feature |", "|---|---|"]
        lines += [f"| {f.id} | {f.title} |" for f in plan.scope]
        lines += ["", "## Risk matrix",
                  "| Feature | Impact | Likelihood | Total | Bucket |",
                  "|---|---|---|---|---|"]
        lines += [f"| {r.feature_id} | {r.impact} | {r.likelihood} | {r.total} | {r.bucket} |"
                  for r in plan.risks]
        lines += ["", "## Test levels per feature",
                  "| Feature | Levels |", "|---|---|"]
        lines += [f"| {fid} | {', '.join(l.value for l in lvls)} |"
                  for fid, lvls in plan.levels.items()]
        lines += ["", "## Entry criteria"] + [f"- {c}" for c in plan.entry_criteria]
        lines += ["", "## Exit criteria"] + [f"- {c}" for c in plan.exit_criteria]
        path = Path(out)
        path.write_text("\n".join(lines))
        return path
```

## Example

```python
plan = (TestPlanBuilder()
        .from_prd("docs/prd-checkout-v2.md")
        .with_timeline(3)
        .build())
TestPlanRenderer().render_markdown(plan, "TEST_PLAN.md")
```

## Common Pitfalls

- Don't skip the risk matrix — a plan without risk scoring is just a TOC.
- Feed `RiskAssessor` real domain keywords; the defaults are starters.
- Exit criteria must be measurable (coverage %, 0 blockers), not vague ("quality is good").
- Timeline should be per-milestone, not whole-project, when scope > 4 weeks.

## Related Skills

- `test-case-writer` — turns each Feature + AC into concrete cases.
- `source-code-audit` — seeds `RiskAssessor` with real hotspots from code.
- `coverage-gap-finder` — informs exit criteria with current coverage %.
- `ci-cd-templates` — wires entry/exit criteria into pipeline gates.
