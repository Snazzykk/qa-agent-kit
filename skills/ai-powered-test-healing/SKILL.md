---
name: ai-powered-test-healing
description: OOP LLM-driven test healing — broader than selector-healer; heals broken assertions, renamed routes, changed Pydantic field names, drifted data-testids. HealingRequest (failing_test + failure_mode + context), TestHealer ABC + ClaudeHealer / OpenAIHealer concretes, HealingProposer returns unified diff patch, HumanApprovalGate writes proposed-heal.patch (requires `git apply` to land), HealingLedger logs every auto-heal with reviewer signoff. Integrates with source-aware-test-gen (fresh graph context). Activate when the user says "auto-heal tests", "fix broken tests", "llm test healing", "self-healing tests".
---

# AI-Powered Test Healing — OOP

**Broader than `selector-healer`.** Heals assertion mismatches, renamed routes, changed Pydantic field names, drifted DOM — any mechanical test breakage where intent is still valid.

## Classes

```python
# tests/framework/healing/models.py
from dataclasses import dataclass, field
from enum import Enum


class FailureMode(str, Enum):
    SELECTOR_NOT_FOUND = "selector_not_found"
    ROUTE_404 = "route_404"
    FIELD_MISSING = "field_missing"
    ASSERTION_MISMATCH = "assertion_mismatch"
    IMPORT_ERROR = "import_error"


@dataclass(slots=True, frozen=True)
class HealingRequest:
    test_path: str
    test_name: str
    failure_mode: FailureMode
    error_message: str
    traceback: str
    source_inventory_snippet: str = ""


@dataclass(slots=True, frozen=True)
class HealProposal:
    diff: str                    # unified diff format
    rationale: str
    confidence: float = 0.0
```

```python
# tests/framework/healing/healers.py
from abc import ABC, abstractmethod

import allure

from .models import HealingRequest, HealProposal


class TestHealer(ABC):
    @abstractmethod
    def propose(self, req: HealingRequest) -> HealProposal: ...


class ClaudeHealer(TestHealer):
    def __init__(self, *, model: str):  # the project's choice, e.g. $HEAL_MODEL
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    @allure.step("Claude heal {req.test_name}")
    def propose(self, req):
        msg = self.client.messages.create(
            model=self.model, max_tokens=2000,
            system=("You fix pytest test failures. Return ONLY a unified diff "
                    "that patches the test file. No commentary outside the diff."),
            messages=[{"role": "user", "content": self._prompt(req)}])
        text = msg.content[0].text if msg.content else ""
        return HealProposal(diff=self._extract_diff(text),
                            rationale="LLM proposed patch", confidence=0.7)

    def _prompt(self, req: HealingRequest) -> str:
        return f"""Failure mode: {req.failure_mode.value}
Test file: {req.test_path}
Test name: {req.test_name}

Error: {req.error_message}

Traceback:
```
{req.traceback[:2000]}
```

Source inventory (real routes / models):
```json
{req.source_inventory_snippet}
```

Emit a unified diff starting with `--- a/{req.test_path}\\n+++ b/{req.test_path}`."""

    @staticmethod
    def _extract_diff(text: str) -> str:
        if "```diff" in text:
            return text.split("```diff", 1)[1].rsplit("```", 1)[0].strip()
        return text.strip()


class OpenAIHealer(TestHealer):
    def __init__(self, model: str = "gpt-4o-2024-11-20"):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model

    def propose(self, req):
        r = self.client.chat.completions.create(
            model=self.model, temperature=0.1,
            messages=[{"role": "system",
                       "content": "Emit a unified diff for the test file. No prose."},
                      {"role": "user", "content": ClaudeHealer._prompt(self, req)}])  # reuse prompt
        return HealProposal(diff=r.choices[0].message.content, rationale="", confidence=0.6)
```

```python
# tests/framework/healing/gate.py
import json
import subprocess
import time
from pathlib import Path

import allure

from .models import HealProposal


class HumanApprovalGate:
    """Writes proposed-heal.patch; CI must `git apply` + humans review the PR diff."""

    def __init__(self, out_dir: str | Path = "artifacts/heals"):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    @allure.step("Write heal patch")
    def write(self, proposal: HealProposal, *, name: str) -> Path:
        p = self.out / f"{name}-{int(time.time())}.patch"
        p.write_text(proposal.diff)
        return p

    def apply_if_confidence_gte(self, proposal: HealProposal, *, threshold: float = 0.9) -> bool:
        if proposal.confidence < threshold:
            return False
        subprocess.run(["git", "apply", "--check", "-"],
                       input=proposal.diff, text=True, check=True)
        subprocess.run(["git", "apply", "-"], input=proposal.diff, text=True, check=True)
        return True


class HealingLedger:
    """Audit trail — every heal gets logged with git sha + reviewer."""

    def __init__(self, path: str | Path = "artifacts/healing-ledger.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, test_name: str, proposal: HealProposal, applied: bool, reviewer: str = ""):
        entry = {"test_name": test_name, "confidence": proposal.confidence,
                 "applied": applied, "reviewer": reviewer,
                 "rationale": proposal.rationale, "timestamp": int(time.time())}
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
```

## Example

```python
from tests.framework.healing.healers import ClaudeHealer
from tests.framework.healing.gate import HumanApprovalGate, HealingLedger
from tests.framework.healing.models import HealingRequest, FailureMode
import json
import os
from pathlib import Path

inv = Path("artifacts/source-inventory.json").read_text()

req = HealingRequest(
    test_path="tests/test_users.py",
    test_name="TestCreateUser::test_happy_path",
    failure_mode=FailureMode.FIELD_MISSING,
    error_message="KeyError: 'userId'",
    traceback="...",
    source_inventory_snippet=inv)

proposal = ClaudeHealer(model=os.environ["HEAL_MODEL"]).propose(req)
patch_path = HumanApprovalGate().write(proposal, name="test_users-heal")
applied = HumanApprovalGate().apply_if_confidence_gte(proposal, threshold=0.9)
HealingLedger().record(test_name=req.test_name, proposal=proposal,
                       applied=applied, reviewer="ci-bot")
```

## Common Pitfalls

- Never auto-apply heals with `confidence < 0.9` — always require human PR review for lower confidence.
- If the underlying SUT behavior changed (not just refactored), healing can mask real regressions. Pair with `differential-testing` against previous release.
- LLM heal prompts burn tokens; rate-limit per-test (e.g. max 3 heal attempts per day).
- Always commit the proposed-heal patch to a branch, not main — even verified heals need PR discussion.

## Related Skills

- `selector-healer` — narrower: Playwright/Selenium locator healing only.
- `source-aware-test-gen` — provides the `source-inventory.json` snippet for the heal prompt.
- `flaky-test-detector` — distinguish "flaky test" from "broken test" before invoking healer.
- `pytest-failure-analyzer` — classifies failures; a known-broken-by-refactor failure is a heal candidate.
