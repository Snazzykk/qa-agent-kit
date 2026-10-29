---
name: flaky-test-detector
description: OOP flaky-test detector — HistoryLoader subclasses for Allure / JUnit / GitHub Actions, FlakinessAnalyzer computes score, StabilizationSuggester maps patterns to fixes, FlakyReport emits markdown + suggests @pytest.mark.flaky quarantine. Activate when the user says "flaky tests", "intermittent failures", "unstable tests".
---

# Flaky Test Detector — OOP

Strict OOP pipeline: **`HistoryLoader` → `FlakinessAnalyzer` → `StabilizationSuggester` → `FlakyReport`.** Each input source is its own concrete loader; all feed the same analyzer.

## When to Activate

- User says "flaky tests", "intermittent failures", "unstable tests".
- Suite has Allure trend data or multiple CI runs archived.
- After `pytest-failure-analyzer` — this aggregates across runs, that classifies one run.

## TestRun

```python
# tests/framework/analysis/test_run.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class TestRun:
    nodeid: str
    status: str              # "passed" | "failed" | "broken" | "skipped"
    duration_s: float
    started_at: datetime
    run_id: str              # CI run / allure history identifier
    trace: str = ""          # failure traceback if any
    retries: int = 0
```

## HistoryLoader (ABC + concretes)

```python
# tests/framework/analysis/history_loader.py
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
import json

import allure
import httpx

from .test_run import TestRun


class HistoryLoader(ABC):
    @abstractmethod
    def load(self) -> list[TestRun]: ...


class AllureHistoryLoader(HistoryLoader):
    """Reads allure-report/history/history-trend.json + per-test history."""

    def __init__(self, report_dir: str | Path) -> None:
        self.root = Path(report_dir)

    @allure.step("Load Allure history from {self.root}")
    def load(self) -> list[TestRun]:
        out: list[TestRun] = []
        for p in (self.root / "data" / "test-cases").glob("*.json"):
            raw = json.loads(p.read_text())
            out.append(TestRun(
                nodeid=raw.get("fullName", raw.get("name", p.stem)),
                status=raw.get("status", "unknown"),
                duration_s=raw.get("time", {}).get("duration", 0.0) / 1000.0,
                started_at=datetime.fromtimestamp(raw.get("time", {}).get("start", 0) / 1000),
                run_id=raw.get("uid", p.stem),
                trace=raw.get("statusDetails", {}).get("trace", ""),
            ))
        return out


class JUnitArchiveLoader(HistoryLoader):
    """Reads a directory of junit-*.xml files (one per historical CI run)."""

    def __init__(self, archive_dir: str | Path) -> None:
        self.root = Path(archive_dir)

    @allure.step("Load JUnit archive from {self.root}")
    def load(self) -> list[TestRun]:
        out: list[TestRun] = []
        for xml_path in sorted(self.root.glob("junit-*.xml")):
            run_id = xml_path.stem
            root = ET.parse(xml_path).getroot()
            for case in root.iter("testcase"):
                failure = case.find("failure") or case.find("error")
                out.append(TestRun(
                    nodeid=f"{case.get('classname')}::{case.get('name')}",
                    status="failed" if failure is not None else "passed",
                    duration_s=float(case.get("time", 0.0)),
                    started_at=datetime.fromtimestamp(xml_path.stat().st_mtime),
                    run_id=run_id,
                    trace=(failure.text or "") if failure is not None else "",
                ))
        return out


class GitHubActionsLoader(HistoryLoader):
    """Pulls workflow runs + their junit artifacts via the GitHub REST API."""

    def __init__(self, *, repo: str, workflow: str, token: str, limit: int = 50) -> None:
        self.repo = repo
        self.workflow = workflow
        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=30.0,
        )
        self.limit = limit

    @allure.step("Load {self.limit} runs from GitHub Actions")
    def load(self) -> list[TestRun]:
        runs = self.client.get(
            f"/repos/{self.repo}/actions/workflows/{self.workflow}/runs",
            params={"per_page": self.limit},
        ).json().get("workflow_runs", [])
        # Real impl downloads each junit artifact, unzips, delegates to JUnitArchiveLoader.
        return [TestRun(
            nodeid=r["name"], status=r["conclusion"] or "unknown", duration_s=0.0,
            started_at=datetime.fromisoformat(r["created_at"].rstrip("Z")), run_id=str(r["id"]),
        ) for r in runs]
```

## FlakinessScore + FlakinessAnalyzer

```python
# tests/framework/analysis/flakiness_analyzer.py
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
import re

import allure

from .test_run import TestRun


@dataclass(slots=True)
class FlakinessScore:
    nodeid: str
    total_runs: int
    fail_count: int
    transitions: int                     # pass↔fail flips between consecutive runs
    dominant_pattern: str = "unknown"    # timing | data | env | selector | unknown

    @property
    def score(self) -> float:
        if self.total_runs == 0:
            return 0.0
        flip_rate = self.transitions / max(self.total_runs - 1, 1)
        fail_rate = self.fail_count / self.total_runs
        return round(min(1.0, flip_rate * 0.7 + fail_rate * 0.3), 3)


class FlakinessAnalyzer:
    _PATTERNS: dict[str, re.Pattern[str]] = {
        "timing":   re.compile(r"Timeout|wait_for_timeout|NotVisible|stale element", re.I),
        "data":     re.compile(r"IntegrityError|duplicate key|UniqueViolation", re.I),
        "env":      re.compile(r"ConnectError|ConnectionError|refused|DNS", re.I),
        "selector": re.compile(r"selector.*not found|no such element|locator resolved to 0", re.I),
    }

    @allure.step("Compute flakiness scores")
    def analyze(self, runs: list[TestRun], min_runs: int = 5, threshold: float = 0.1) -> list[FlakinessScore]:
        by_node: dict[str, list[TestRun]] = defaultdict(list)
        for r in runs:
            by_node[r.nodeid].append(r)
        scores: list[FlakinessScore] = []
        for nodeid, entries in by_node.items():
            if len(entries) < min_runs:
                continue
            entries.sort(key=lambda x: x.started_at)
            statuses = [e.status for e in entries]
            transitions = sum(1 for a, b in zip(statuses, statuses[1:]) if a != b)
            fail_count = sum(1 for s in statuses if s in {"failed", "broken"})
            score = FlakinessScore(
                nodeid=nodeid, total_runs=len(entries), fail_count=fail_count, transitions=transitions,
                dominant_pattern=self._dominant_pattern(entries),
            )
            if score.score >= threshold:
                scores.append(score)
        return sorted(scores, key=lambda s: s.score, reverse=True)

    def _dominant_pattern(self, entries: list[TestRun]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for e in entries:
            for name, rx in self._PATTERNS.items():
                if rx.search(e.trace):
                    counts[name] += 1
        return max(counts, key=counts.get) if counts else "unknown"
```

## StabilizationSuggester

```python
# tests/framework/analysis/stabilization_suggester.py
from __future__ import annotations
from dataclasses import dataclass

import allure

from .flakiness_analyzer import FlakinessScore


@dataclass(slots=True)
class Suggestion:
    fix: str
    marker: str | None = None   # @pytest.mark.flaky — the quarantine marker pytest-bootstrap registers


class StabilizationSuggester:
    _FIXES: dict[str, str] = {
        "timing":   "Replace sleeps with Playwright `expect(...).to_be_visible(timeout=...)` auto-waits.",
        "data":     "Isolate per-test Faker seed; wrap DB writes in transactional rollback.",
        "env":      "Add healthcheck before suite; retry ConnectError once at session fixture.",
        "selector": "Run `selector-healer` skill; prefer data-testid > role > label.",
        "unknown":  "Re-run with `-p no:randomly --count=10`; capture a consistent trace.",
    }

    @allure.step("Suggest fix for {score.nodeid}")
    def suggest(self, score: FlakinessScore) -> Suggestion:
        fix = self._FIXES.get(score.dominant_pattern, self._FIXES["unknown"])
        marker = "@pytest.mark.flaky" if score.score >= 0.5 else None
        return Suggestion(fix=fix, marker=marker)
```

## FlakyReport

```python
# tests/framework/analysis/flaky_report.py
from __future__ import annotations
from pathlib import Path

import allure

from .flakiness_analyzer import FlakinessScore
from .stabilization_suggester import StabilizationSuggester


class FlakyReport:
    def __init__(self, suggester: StabilizationSuggester | None = None) -> None:
        self.suggester = suggester or StabilizationSuggester()

    @allure.step("Render flaky-report to {out}")
    def render(self, scores: list[FlakinessScore], out: str | Path = "flaky-report.md") -> Path:
        lines = ["# Flaky Test Report", "",
                 "| Test | Score | Fails | Runs | Pattern | Fix |", "|---|---|---|---|---|---|"]
        for s in scores:
            sug = self.suggester.suggest(s)
            lines.append(f"| `{s.nodeid}` | {s.score} | {s.fail_count} | {s.total_runs} | {s.dominant_pattern} | {sug.fix} |")
        quarantine = [s for s in scores if self.suggester.suggest(s).marker]
        if quarantine:
            lines += ["", "## Suggested quarantine markers", ""]
            lines += [f"- `{s.nodeid}` — add `@pytest.mark.flaky` (excluded by `-m \"not flaky\"`)" for s in quarantine]
        path = Path(out)
        path.write_text("\n".join(lines))
        return path
```

## Common Pitfalls

- Need at least 5 runs per test to be meaningful (`min_runs=5`).
- `@pytest.mark.flaky` is a quarantine, not a fix — always open a ticket per score.
- Don't mix dev-laptop history with CI history; filter by `run_id` prefix.
- Tests that always fail aren't flaky — exclude `score == 1.0` from quarantine.

## Related Skills

- `pytest-failure-analyzer` — shares `FailurePattern` taxonomy for single-run classification.
- `allure-report-insights` — consumes same `allure-results/`.
- `selector-healer` — fixes the dominant "selector" pattern.
- `e2e-test-suite-refactor` — structural fixes for recurring timing flakes.
