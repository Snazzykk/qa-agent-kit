---
name: selector-healer
description: OOP selector healing for Playwright / Selenium — SelectorHealer class loads failing locator, fetches live DOM, scores alternative strategies (data-testid > role > label > text > css), applies batch update across pages and tests, writes healing-log.md. Activate when the user says "selector broken", "locator healing", "update selectors after UI change".
---

# Selector Healer — OOP

Class-based healing pipeline that keeps the project consistent with the selector priority used in `page-object-generator` and `arch-playwright-pom`.

## OOP Model

```python
# tests/tools/selector_healer.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import allure
from playwright.sync_api import Page


@dataclass(slots=True)
class BrokenLocator:
    file: Path
    lineno: int
    expr: str           # original expression from source code
    page_url: str


@dataclass(slots=True, frozen=True)
class Candidate:
    expr: str
    strategy: str       # "testid" / "role" / "label" / "text" / "css"
    score: int          # 100 testid > 80 role > 70 label > 60 text > 30 css
    unique: bool        # only one matching element in DOM


class LocatorInspector:
    """Load the failing element's context from failure traceback or test file."""

    def from_failure(self, trace: str) -> BrokenLocator: ...
    def from_file(self, path: Path, lineno: int) -> BrokenLocator: ...


class CandidateRanker:
    """Given a DOM + the old locator's element, rank alternative selectors."""

    WEIGHTS: dict[str, int] = {"testid": 100, "role": 80, "label": 70, "text": 60, "css": 30}

    def rank(self, element_html: str, dom: str) -> list[Candidate]: ...


class SelectorHealer:
    """Pipeline: Broken locator → DOM → Candidates → patch files → log."""

    def __init__(self, page: Page, project_root: Path):
        self.page = page
        self.project_root = project_root
        self.inspector = LocatorInspector()
        self.ranker = CandidateRanker()

    @allure.step("Heal {broken.file}:{broken.lineno}")
    def heal(self, broken: BrokenLocator) -> Candidate | None:
        self.page.goto(broken.page_url)
        self.page.wait_for_load_state("networkidle")
        element_html = self._resolve_element(broken.expr)
        if element_html is None:
            return None  # element truly missing — not a selector issue
        dom = self.page.content()
        candidates = self.ranker.rank(element_html, dom)
        best = next((c for c in candidates if c.unique and c.score >= 60), None)
        return best

    @allure.step("Batch-apply {len(replacements)} replacements")
    def apply_batch(self, replacements: dict[str, Candidate]) -> None:
        """{old_expr: Candidate} → rewrite files atomically, log diff."""
        ...

    def _resolve_element(self, expr: str) -> str | None: ...
```

## Healing Policies

- **Never** replace with a non-unique candidate — anchor via parent component (`OrderRow(row_loc).click_edit()`) or emit TODO.
- **Never** drop to CSS if any semantic option exists.
- If no `data-testid` in DOM, recommend "add `data-testid` on `<TargetComponent>`" in the log — keep the old locator untouched.
- When multiple broken locators share a root element, generate a `BaseComponent` in `base_components/` and migrate all usages in one pass.

## `healing-log.md` Output

```markdown
## Selector healing — 2026-04-21

### ✓ Healed (4)
| File | Line | Old | New | Score |
|------|------|-----|-----|-------|
| pages/login_page.py | 14 | `//input[@id='login']` | `page.get_by_test_id('email-input')` | 100 |
| pages/cart_page.py | 22 | `.remove-btn:nth-child(1)` | `page.get_by_role('button', name='Remove')` | 80 |

### ⚠ TODO for reviewer (2)
- pages/pay_page.py:48 — current DOM has no `data-testid`; upgrade is CSS-only. Ask team to add `data-testid="pay-now"`.

### ✂ Files rewritten
- pages/login_page.py — 1 replacement
- pages/cart_page.py — 3 replacements (+ 1 component extracted to `base_components/cart_row.py`)
```

## Orchestrator Usage

```python
from tests.tools.selector_healer import SelectorHealer, LocatorInspector

# From a pytest failure log
broken = LocatorInspector().from_failure(Path("artifacts/last-failure.txt").read_text())
healer = SelectorHealer(page, project_root=Path("."))
best = healer.heal(broken)
if best:
    healer.apply_batch({broken.expr: best})
```

## Related Skills

- `page-object-generator` — same selector priority map.
- `arch-playwright-pom` / `arch-selenium-pom` — prerequisite.
- `flaky-test-detector` — broken locators surface as flakiness; pair with it.
- `test-code-review` — proactive catch before merge.
