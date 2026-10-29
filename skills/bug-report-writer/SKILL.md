---
name: bug-report-writer
description: OOP bug report builder — BugReport dataclass, BugReportBuilder fluent interface (.with_failure / .with_env / .with_severity / .with_attachments), FailureExtractor reads pytest/Allure artifacts, BugRenderer emits Jira wiki + Linear Markdown. Activate when the user says "write bug report", "format bug", "bug from failure".
---

# Bug Report Writer — OOP

Strict OOP pipeline: **`FailureExtractor` → `BugReportBuilder` → `BugReport` → `BugRenderer`.** No ad-hoc string templates; every report is a typed object with pluggable renderers.

## When to Activate

- User says "write bug report", "format bug", "bug from failure".
- CI job failed and the user needs a ticket-ready artifact.
- After `pytest-failure-analyzer` classifies a group worth filing.
- Before `jira-workflow` / `linear-workflow` post the result upstream.

## Severity

```python
# tests/framework/reporting/bug/severity.py
from __future__ import annotations
from enum import Enum


class Severity(str, Enum):
    BLOCKER = "Blocker"
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    TRIVIAL = "Trivial"
```

## BugReport dataclass

```python
# tests/framework/reporting/bug/bug_report.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from .severity import Severity


@dataclass(slots=True, frozen=True)
class BugReport:
    title: str
    steps: tuple[str, ...]
    expected: str
    actual: str
    severity: Severity
    environment: dict[str, str] = field(default_factory=dict)
    attachments: tuple[Path, ...] = ()
    labels: tuple[str, ...] = ()
    source_test_id: str | None = None
```

## FailureExtractor (pytest + Allure artifacts)

```python
# tests/framework/reporting/bug/failure_extractor.py
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

import allure


@dataclass(slots=True, frozen=True)
class FailureEntry:
    nodeid: str
    message: str
    traceback: str
    attachments: tuple[Path, ...] = ()


class FailureExtractor:
    """Reads pytest text traceback or allure-results/ JSON and yields FailureEntry seeds."""

    @allure.step("Extract failure from pytest traceback")
    def from_pytest(self, *, nodeid: str, traceback: str) -> FailureEntry:
        headline = next(
            (ln.lstrip("E ").strip() for ln in traceback.splitlines() if ln.startswith("E ")),
            traceback.strip().splitlines()[-1] if traceback.strip() else "",
        )
        return FailureEntry(nodeid=nodeid, message=headline, traceback=traceback)

    @allure.step("Extract failure from allure-results {results_dir}")
    def from_allure(self, results_dir: str | Path) -> list[FailureEntry]:
        out: list[FailureEntry] = []
        for p in Path(results_dir).glob("*-result.json"):
            raw = json.loads(p.read_text())
            if raw.get("status") not in {"failed", "broken"}:
                continue
            status = raw.get("statusDetails", {})
            atts = tuple(Path(results_dir) / a["source"] for a in raw.get("attachments", []))
            out.append(FailureEntry(
                nodeid=raw.get("fullName", raw.get("name", p.stem)),
                message=status.get("message", ""),
                traceback=status.get("trace", ""),
                attachments=atts,
            ))
        return out
```

## BugReportBuilder (fluent)

```python
# tests/framework/reporting/bug/bug_report_builder.py
from __future__ import annotations
from pathlib import Path
from typing import Self

import allure

from tests.framework.config.settings import Settings

from .bug_report import BugReport
from .failure_extractor import FailureEntry
from .severity import Severity


class BugReportBuilder:
    """Fluent builder; every `.with_*` returns Self; `.build()` is terminal."""

    def __init__(self) -> None:
        self._title: str = ""
        self._steps: list[str] = []
        self._expected: str = ""
        self._actual: str = ""
        self._severity: Severity = Severity.MAJOR
        self._env: dict[str, str] = {}
        self._attachments: list[Path] = []
        self._labels: list[str] = []
        self._source_test_id: str | None = None

    @allure.step("Seed bug from failure {failure.nodeid}")
    def with_failure(self, failure: FailureEntry) -> Self:
        self._title = failure.message[:120] or "Test failed"
        self._actual = failure.message
        self._source_test_id = failure.nodeid
        self._steps = [f"Run `pytest '{failure.nodeid}'`"]
        self._attachments.extend(failure.attachments)
        return self

    def with_env(self, settings: Settings) -> Self:
        self._env = {
            "BASE_URL": settings.BASE_URL,
            "PYTHON": "3.10+",
            "SUITE": "pytest",
        }
        return self

    def with_severity(self, severity: Severity) -> Self:
        self._severity = severity
        return self

    def with_expected(self, expected: str) -> Self:
        self._expected = expected
        return self

    def with_steps(self, *steps: str) -> Self:
        self._steps = list(steps)
        return self

    def with_attachment(self, path: str | Path) -> Self:
        self._attachments.append(Path(path))
        return self

    def with_label(self, label: str) -> Self:
        self._labels.append(label)
        return self

    @allure.step("Build BugReport")
    def build(self) -> BugReport:
        return BugReport(
            title=self._title,
            steps=tuple(self._steps),
            expected=self._expected,
            actual=self._actual,
            severity=self._severity,
            environment=dict(self._env),
            attachments=tuple(self._attachments),
            labels=tuple(self._labels),
            source_test_id=self._source_test_id,
        )
```

## BugRenderer (ABC + concretes)

```python
# tests/framework/reporting/bug/bug_renderer.py
from __future__ import annotations
from abc import ABC, abstractmethod

import allure

from .bug_report import BugReport


class BugRenderer(ABC):
    @abstractmethod
    def render(self, report: BugReport) -> str: ...


class JiraWikiRenderer(BugRenderer):
    @allure.step("Render Jira wiki")
    def render(self, report: BugReport) -> str:
        steps = "\n".join(f"# {s}" for s in report.steps) or "_n/a_"
        env = "\n".join(f"|{k}|{v}|" for k, v in report.environment.items()) or "|-|-|"
        atts = "\n".join(f"* [^{p.name}]" for p in report.attachments) or "_none_"
        return (
            f"h2. {report.title}\n\n"
            f"*Severity:* {report.severity.value}\n\n"
            f"h3. Steps\n{steps}\n\n"
            f"h3. Expected\n{report.expected}\n\n"
            f"h3. Actual\n{{code}}\n{report.actual}\n{{code}}\n\n"
            f"h3. Environment\n||key||value||\n{env}\n\n"
            f"h3. Attachments\n{atts}\n"
        )


class LinearMarkdownRenderer(BugRenderer):
    @allure.step("Render Linear Markdown")
    def render(self, report: BugReport) -> str:
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(report.steps, 1)) or "_n/a_"
        env = "\n".join(f"- **{k}**: `{v}`" for k, v in report.environment.items())
        atts = "\n".join(f"- `{p}`" for p in report.attachments) or "_none_"
        return (
            f"# {report.title}\n\n"
            f"**Severity:** {report.severity.value}  \n"
            f"**Source test:** `{report.source_test_id or 'n/a'}`\n\n"
            f"## Steps\n{steps}\n\n"
            f"## Expected\n{report.expected}\n\n"
            f"## Actual\n```\n{report.actual}\n```\n\n"
            f"## Environment\n{env}\n\n"
            f"## Attachments\n{atts}\n"
        )
```

## Example: pytest hook that auto-files on failure

```python
# tests/conftest.py
import pytest

from tests.framework.reporting.bug.bug_report_builder import BugReportBuilder
from tests.framework.reporting.bug.bug_renderer import LinearMarkdownRenderer
from tests.framework.reporting.bug.failure_extractor import FailureExtractor
from tests.framework.reporting.bug.severity import Severity


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        entry = FailureExtractor().from_pytest(nodeid=item.nodeid, traceback=str(report.longrepr))
        bug = (BugReportBuilder()
               .with_failure(entry)
               .with_env(item.config._settings)
               .with_severity(Severity.MAJOR)
               .with_expected("Test passes in clean env.")
               .build())
        (item.config.rootpath / "bug-reports" / f"{item.name}.md").write_text(
            LinearMarkdownRenderer().render(bug)
        )
```

## Common Pitfalls

- Don't inline markdown strings in test code — always route through a `BugRenderer`.
- Jira wiki != Markdown; pick the renderer matching the destination tool.
- Scrub secrets from `environment` before rendering (tokens, emails).
- Attach screenshots by Path only; never embed base64 in the report body.

## Related Skills

- `pytest-failure-analyzer` — classifies failures; feeds `FailureExtractor`.
- `jira-workflow` — posts Jira-wiki output via `JiraPoster.comment`.
- `linear-workflow` — posts Linear-markdown output via `LinearPoster`.
- `production-error-to-regression-test` — promote the filed bug into a pytest regression.
