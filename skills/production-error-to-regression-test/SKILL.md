---
name: production-error-to-regression-test
description: OOP Sentry/DD error → failing regression test — ErrorSource ABC (SentrySource / DatadogSource / PasteSource), ErrorExtractor parses stacktrace + request + user state, RegressionTestBuilder emits pytest class using BaseAPIClient / BasePage patterns, placed in correct tests/ module. Activate when the user says "sentry to test", "regression from error", "incident to test".
---

# Production Error → Regression Test — OOP

Strict OOP pipeline: **`ErrorSource` → `ErrorExtractor` → `PIIScrubber` → `TestPlacer` → `RegressionTestBuilder`.** Every incident becomes a pytest class that inherits the project's `BaseTest` / `BaseAuthenticatedTest`, marked `@pytest.mark.regression` and tagged with the incident ID.

## When to Activate

- User says "sentry to test", "regression from error", "incident to test", "add a regression test for this stacktrace".
- Incident post-mortem requires a guarding test before closing.
- Sentry / Datadog issue has recurred and deserves a permanent fixture.

## ErrorEvent dataclass

```python
# tests/framework/incidents/error_event.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class StackFrame:
    filename: str
    function: str
    lineno: int
    in_app: bool = True


@dataclass(slots=True, frozen=True)
class ErrorEvent:
    exception_type: str           # e.g. "IntegrityError"
    message: str
    stack_frames: tuple[StackFrame, ...]
    request_payload: dict = field(default_factory=dict)
    user_state: dict = field(default_factory=dict)
    env: str = "production"
    release_sha: str | None = None
    url: str | None = None
    incident_id: str = ""         # INC-YYYY-MMDD-slug
```

## ErrorSource (ABC + concretes)

```python
# tests/framework/incidents/sources.py
from __future__ import annotations
import json
import os
from abc import ABC, abstractmethod

import allure
import httpx

from .error_event import ErrorEvent, StackFrame


class ErrorSource(ABC):
    @abstractmethod
    def fetch(self) -> ErrorEvent: ...


class SentrySource(ErrorSource):
    """httpx-based fetcher. Auth via env SENTRY_TOKEN."""

    def __init__(self, *, org: str, issue_id: str, token: str | None = None) -> None:
        self.org = org
        self.issue_id = issue_id
        self.token = token or os.environ["SENTRY_TOKEN"]

    @allure.step("Fetch Sentry issue {self.issue_id}")
    def fetch(self) -> ErrorEvent:
        r = httpx.get(
            f"https://sentry.io/api/0/organizations/{self.org}/issues/{self.issue_id}/events/latest/",
            headers={"Authorization": f"Bearer {self.token}"}, timeout=10.0,
        )
        r.raise_for_status()
        raw = r.json()
        frames = tuple(
            StackFrame(filename=f.get("filename", ""), function=f.get("function", ""),
                       lineno=int(f.get("lineNo") or 0), in_app=bool(f.get("inApp")))
            for e in raw.get("entries", []) if e.get("type") == "exception"
            for f in e["data"]["values"][0]["stacktrace"]["frames"]
        )
        exc = raw["entries"][0]["data"]["values"][0]
        return ErrorEvent(
            exception_type=exc.get("type", ""),
            message=exc.get("value", ""),
            stack_frames=frames,
            request_payload=next((e["data"] for e in raw.get("entries", []) if e["type"] == "request"), {}),
            user_state=raw.get("user", {}),
            env=raw.get("environment", "production"),
            release_sha=raw.get("release"),
            url=raw.get("culprit"),
            incident_id=f"SENTRY-{self.issue_id}",
        )


class DatadogSource(ErrorSource):
    """Wraps datadog-api-client. Auth via DD_API_KEY / DD_APP_KEY."""

    def __init__(self, *, event_id: str) -> None:
        self.event_id = event_id

    @allure.step("Fetch Datadog event {self.event_id}")
    def fetch(self) -> ErrorEvent:
        from datadog_api_client import ApiClient, Configuration
        from datadog_api_client.v2.api.events_api import EventsApi
        with ApiClient(Configuration()) as client:
            raw = EventsApi(client).get_event(self.event_id).to_dict()
        attrs = raw["data"]["attributes"]
        return ErrorEvent(
            exception_type=attrs.get("error_type", ""),
            message=attrs.get("message", ""),
            stack_frames=(),
            incident_id=f"DD-{self.event_id}",
        )


class PasteSource(ErrorSource):
    """Pasted JSON or raw traceback text."""

    def __init__(self, text: str) -> None:
        self.text = text

    @allure.step("Parse pasted error")
    def fetch(self) -> ErrorEvent:
        try:
            raw = json.loads(self.text)
            return ErrorEvent(**raw)
        except json.JSONDecodeError:
            first_line = self.text.strip().splitlines()[-1] if self.text.strip() else ""
            exc_type, _, msg = first_line.partition(":")
            return ErrorEvent(exception_type=exc_type.strip(), message=msg.strip(),
                              stack_frames=(), incident_id="PASTED")
```

## ErrorExtractor + PIIScrubber

```python
# tests/framework/incidents/extractor.py
from __future__ import annotations
import re
from dataclasses import replace

import allure

from .error_event import ErrorEvent, StackFrame


class PIIScrubber:
    """Redact common PII before the event ends up in test source."""

    _EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    _TOKEN = re.compile(r"(?i)(bearer|token|secret|apikey)[=:\s]+\S+")
    _CARD  = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

    def scrub_text(self, text: str) -> str:
        text = self._EMAIL.sub("user@example.com", text)
        text = self._TOKEN.sub(r"\1=<redacted>", text)
        text = self._CARD.sub("<redacted-card>", text)
        return text

    def scrub(self, event: ErrorEvent) -> ErrorEvent:
        return replace(event,
                       message=self.scrub_text(event.message),
                       request_payload={k: self.scrub_text(str(v)) for k, v in event.request_payload.items()},
                       user_state={"id": "<redacted>"})


class ErrorExtractor:
    """Trim to in-app frames; identify likely reproduction hook."""

    def __init__(self, scrubber: PIIScrubber | None = None) -> None:
        self._scrubber = scrubber or PIIScrubber()

    @allure.step("Extract minimal repro")
    def extract(self, event: ErrorEvent) -> ErrorEvent:
        event = self._scrubber.scrub(event)
        in_app = tuple(f for f in event.stack_frames if f.in_app) or event.stack_frames
        return replace(event, stack_frames=in_app)

    def repro_frame(self, event: ErrorEvent) -> StackFrame | None:
        return next(iter(event.stack_frames), None)
```

## TestPlacer

```python
# tests/framework/incidents/test_placer.py
from __future__ import annotations
import re
from pathlib import Path

from .error_event import ErrorEvent


class TestPlacer:
    """Map src/billing/refund.py:48 → tests/test_billing.py."""

    _SRC_RE = re.compile(r"(?:src/)?(?P<module>[\w/]+)\.py")

    def __init__(self, tests_root: str | Path = "tests") -> None:
        self.tests_root = Path(tests_root)

    def decide(self, event: ErrorEvent) -> Path:
        frame = next((f for f in event.stack_frames if f.in_app), None)
        if frame is None:
            return self.tests_root / "regression" / "test_unknown.py"
        m = self._SRC_RE.search(frame.filename)
        if not m:
            return self.tests_root / "regression" / "test_unknown.py"
        top_pkg = m.group("module").split("/")[0]
        return self.tests_root / f"test_{top_pkg}.py"
```

## RegressionTestBuilder (fluent)

```python
# tests/framework/incidents/regression_test_builder.py
from __future__ import annotations
from datetime import date
from typing import Self

import allure

from .error_event import ErrorEvent


class RegressionTestBuilder:
    """Emit a pytest class inheriting BaseTest/BaseAuthenticatedTest, marked regression + case id."""

    def __init__(self) -> None:
        self._event: ErrorEvent | None = None
        self._fix_sha: str | None = None
        self._base_class: str = "BaseAuthenticatedTest"

    def with_event(self, event: ErrorEvent) -> Self:
        self._event = event
        return self

    def with_fix_commit(self, sha: str) -> Self:
        self._fix_sha = sha
        return self

    def with_base_class(self, name: str) -> Self:
        self._base_class = name
        return self

    def _slug(self, text: str) -> str:
        return "-".join(w.lower() for w in text.split()[:5] if w.isalnum())[:40]

    @allure.step("Render regression test class")
    def build(self) -> str:
        assert self._event is not None, "call .with_event() first"
        ev = self._event
        today = date.today().strftime("%Y-%m%d")
        case_id = ev.incident_id or f"INC-{today}-{self._slug(ev.message)}"
        class_name = "Test" + "".join(w.title() for w in self._slug(ev.message).split("-")) or "TestRegression"
        frame = ev.stack_frames[0] if ev.stack_frames else None
        endpoint = ev.url or "/"
        return (
            "from __future__ import annotations\n"
            "import allure\n"
            "import pytest\n\n"
            f"from tests.framework.base_test import {self._base_class}\n"
            "from tests.framework.assertions import Assertions\n\n\n"
            "@allure.feature(\"Regression\")\n"
            f"@allure.story(\"{case_id}\")\n"
            "@pytest.mark.regression\n"
            f"@pytest.mark.case(\"{case_id}\")\n"
            f"class {class_name}({self._base_class}):\n"
            f"    \"\"\"Guards against {ev.exception_type}: {ev.message}\n\n"
            f"    Source: {frame.filename if frame else 'n/a'}:{frame.lineno if frame else 0}\n"
            f"    Fix: {self._fix_sha or '<pending>'}\n"
            "    \"\"\"\n\n"
            "    def test_does_not_raise(self):\n"
            f"        response = self.client.post(\"{endpoint}\", json={dict(ev.request_payload)!r})\n"
            "        Assertions.assert_status(response, 200)\n"
        )
```

## Example

```python
event = ErrorExtractor().extract(SentrySource(org="acme", issue_id="1234").fetch())
path = TestPlacer().decide(event)
source = (RegressionTestBuilder()
          .with_event(event)
          .with_fix_commit("a1b2c3d")
          .build())
path.write_text(source)
```

## Common Pitfalls

- Never commit test fixtures containing real PII — always route through `PIIScrubber`.
- If the top in-app frame is in vendored code, escalate to the user; don't place in `tests/vendor/`.
- A failing regression test without a linked fix commit is a pending alarm — add `@pytest.mark.xfail(strict=False)` if fix is in flight.
- Don't inline the real user id; use anonymised fixtures from `test-data-factory`.

## Related Skills

- `pytest-failure-analyzer` — sibling: classifies test failures, this classifies prod errors.
- `bug-report-writer` — file the incident to Jira/Linear before the test lands.
- `test-data-factory` — anonymised fixtures for the repro payload.
- `ci-cd-templates` — add a `regression` job that runs `-m regression` nightly.
