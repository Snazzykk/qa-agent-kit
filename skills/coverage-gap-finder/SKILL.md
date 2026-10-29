---
name: coverage-gap-finder
description: OOP coverage-gap finder — CoverageLoader reads coverage.xml / .coverage, ChurnAnalyzer reads git log, RiskScorer combines (1-coverage) × log(1+commits), HotspotRanker returns top-N, CoverageReport emits markdown. Activate when the user says "coverage gaps", "what to test next", "risk-based testing".
---

# Coverage Gap Finder — OOP

Strict OOP pipeline: **`CoverageLoader` → `ChurnAnalyzer` → `RiskScorer` → `HotspotRanker` → `CoverageReport`.** Risk-weighted module ranking replaces flat coverage tables.

## When to Activate

- User has `coverage.xml` / `.coverage` and asks "what to test next".
- User says "coverage gaps", "risk-based testing", "hotspot analysis".
- Before sprint planning — output feeds `test-plan-generator`.

## CoverageEntry + ChurnEntry

```python
# tests/framework/analysis/coverage_entry.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CoverageEntry:
    module: str              # dotted or path
    filename: str            # absolute or repo-relative file path
    statements: int
    missed: int

    @property
    def coverage(self) -> float:
        return 1.0 - (self.missed / self.statements) if self.statements else 1.0


@dataclass(slots=True, frozen=True)
class ChurnEntry:
    filename: str
    commits: int
    lines_changed: int
```

## CoverageLoader (ABC + concretes)

```python
# tests/framework/analysis/coverage_loader.py
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from xml.etree import ElementTree as ET
import sqlite3

import allure

from .coverage_entry import CoverageEntry


class CoverageLoader(ABC):
    @abstractmethod
    def load(self) -> list[CoverageEntry]: ...


class CoberturaXmlLoader(CoverageLoader):
    """Reads coverage.xml (Cobertura format, default pytest-cov output)."""

    def __init__(self, path: str | Path = "coverage.xml") -> None:
        self.path = Path(path)

    @allure.step("Load Cobertura from {self.path}")
    def load(self) -> list[CoverageEntry]:
        root = ET.parse(self.path).getroot()
        out: list[CoverageEntry] = []
        for cls in root.iter("class"):
            lines = list(cls.iter("line"))
            statements = len(lines)
            missed = sum(1 for ln in lines if int(ln.get("hits", 0)) == 0)
            filename = cls.get("filename", "")
            out.append(CoverageEntry(
                module=cls.get("name", filename.replace("/", ".").rstrip(".py")),
                filename=filename,
                statements=statements,
                missed=missed,
            ))
        return out


class CoveragePyLoader(CoverageLoader):
    """Reads the native `.coverage` SQLite DB (coverage.py 5+)."""

    def __init__(self, path: str | Path = ".coverage") -> None:
        self.path = Path(path)

    @allure.step("Load .coverage SQLite from {self.path}")
    def load(self) -> list[CoverageEntry]:
        conn = sqlite3.connect(str(self.path))
        try:
            rows = conn.execute("""
                SELECT file.path,
                       COUNT(DISTINCT line_bits.line) AS stmts,
                       SUM(CASE WHEN line_bits.line IS NULL THEN 1 ELSE 0 END) AS missed
                FROM file LEFT JOIN line_bits ON file.id = line_bits.file_id
                GROUP BY file.path
            """).fetchall()
        finally:
            conn.close()
        return [CoverageEntry(
            module=Path(path).with_suffix("").as_posix().replace("/", "."),
            filename=path, statements=stmts or 0, missed=missed or 0,
        ) for path, stmts, missed in rows]
```

## ChurnAnalyzer

```python
# tests/framework/analysis/churn_analyzer.py
from __future__ import annotations
from collections import defaultdict
import subprocess

import allure

from .coverage_entry import ChurnEntry


class ChurnAnalyzer:
    """Runs `git log --no-merges --numstat` and counts commits + lines changed per file."""

    def __init__(self, *, days: int = 90, repo: str = ".") -> None:
        self.days = days
        self.repo = repo

    @allure.step("Analyze churn over last {self.days} days")
    def analyze(self) -> dict[str, ChurnEntry]:
        cmd = [
            "git", "-C", self.repo, "log", "--no-merges", "--numstat",
            f"--since={self.days}.days.ago", "--pretty=format:__COMMIT__",
        ]
        output = subprocess.check_output(cmd, text=True, errors="ignore")
        commits: dict[str, int] = defaultdict(int)
        lines: dict[str, int] = defaultdict(int)
        current_files: set[str] = set()
        for line in output.splitlines():
            if line == "__COMMIT__":
                for f in current_files:
                    commits[f] += 1
                current_files.clear()
                continue
            parts = line.split("\t")
            if len(parts) == 3 and parts[2]:
                added, removed, filename = parts
                current_files.add(filename)
                if added.isdigit() and removed.isdigit():
                    lines[filename] += int(added) + int(removed)
        for f in current_files:
            commits[f] += 1
        return {f: ChurnEntry(filename=f, commits=commits[f], lines_changed=lines[f]) for f in commits}
```

## RiskScorer + HotspotRanker

```python
# tests/framework/analysis/risk_scorer.py
from __future__ import annotations
from dataclasses import dataclass
import math

import allure

from .coverage_entry import CoverageEntry, ChurnEntry


@dataclass(slots=True)
class RiskEntry:
    filename: str
    coverage: float
    commits: int
    lines_changed: int
    score: float


class RiskScorer:
    """score = (1 - coverage) * log(1 + commits) — high churn + low coverage = hot."""

    @allure.step("Score modules")
    def score(
        self,
        coverage_entries: list[CoverageEntry],
        churn_by_file: dict[str, ChurnEntry],
    ) -> list[RiskEntry]:
        out: list[RiskEntry] = []
        for entry in coverage_entries:
            churn = churn_by_file.get(entry.filename)
            commits = churn.commits if churn else 0
            lines_changed = churn.lines_changed if churn else 0
            risk = (1.0 - entry.coverage) * math.log1p(commits)
            out.append(RiskEntry(
                filename=entry.filename, coverage=round(entry.coverage, 3),
                commits=commits, lines_changed=lines_changed, score=round(risk, 3),
            ))
        return out


class HotspotRanker:
    """Returns the top-N highest-risk modules."""

    def __init__(self, top_n: int = 15) -> None:
        self.top_n = top_n

    @allure.step("Rank top {self.top_n} hotspots")
    def rank(self, entries: list[RiskEntry]) -> list[RiskEntry]:
        return sorted([e for e in entries if e.score > 0], key=lambda e: e.score, reverse=True)[: self.top_n]
```

## CoverageReport

```python
# tests/framework/analysis/coverage_report.py
from __future__ import annotations
from pathlib import Path

import allure

from .risk_scorer import RiskEntry


class CoverageReport:
    @allure.step("Render coverage-gap report to {out}")
    def render(self, hotspots: list[RiskEntry], out: str | Path = "coverage-gaps.md") -> Path:
        lines = [
            "# Coverage Gap Report", "",
            "Risk = (1 − coverage) × log(1 + commits_90d). Top hotspots first.", "",
            "| File | Coverage | Commits (90d) | Lines Δ | Risk |", "|---|---|---|---|---|",
        ]
        for e in hotspots:
            lines.append(f"| `{e.filename}` | {e.coverage:.1%} | {e.commits} | {e.lines_changed} | **{e.score}** |")
        lines += ["", "## Suggested next steps", ""]
        for e in hotspots[:5]:
            lines.append(f"- Add unit tests for `{e.filename}` (coverage {e.coverage:.1%}, {e.commits} commits).")
        path = Path(out)
        path.write_text("\n".join(lines))
        return path
```

## Common Pitfalls

- `git log` must be run from the repo root; pass `repo="/abs/path"` in CI containers.
- File paths in `coverage.xml` vs git differ — normalize by stripping `src/` prefix if needed.
- 90-day window captures recent risk; widen for stable long-lived modules.
- Score of `0` means no churn OR perfect coverage — both are fine, skip them.

## Related Skills

- `pytest-bootstrap` — installs pytest-cov for `.coverage`.
- `ci-cd-templates` — emit `coverage.xml` artifact per run.
- `test-plan-generator` — consume top hotspots as planned test targets.
- `source-code-audit` — alternative input (AST-based) when coverage is missing.
