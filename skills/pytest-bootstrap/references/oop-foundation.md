# Pytest Bootstrap — OOP Foundation

Strict OOP pytest setup. **Every test MUST live inside a class.** No bare functions.

## When to Activate

- Fresh project with no `tests/` or no `pytest.ini` / `[tool.pytest.ini_options]`.
- Before `api-test-generator`, `playwright-bootstrap`, `allure-reporting`.
- User says "set up pytest", "initialize pytest", "add tests", "pytest config".

## RULE: No Bare Functions

```python
# WRONG — procedural, no encapsulation
def test_health():
    assert app.get("/health").status_code == 200

# CORRECT — OOP, inherits BaseTest
@allure.feature("Health")
class TestHealth(BaseTest):
    def test_health_returns_200(self):
        response = self.client.get("/health")
        Assertions.assert_status(response, 200)
```

## Base Class Hierarchy

```python
# tests/framework/base_test.py
from __future__ import annotations

import allure
import pytest

from tests.framework.config.settings import Settings
from tests.framework.clients.http_client import HTTPClient


class BaseTest:
    """Base class for ALL test classes. Non-negotiable."""

    client: HTTPClient
    settings: Settings

    @pytest.fixture(autouse=True)
    def _setup_base(self, http_client: HTTPClient, settings: Settings) -> None:
        self.client = http_client
        self.settings = settings


class BaseAuthenticatedTest(BaseTest):
    """Base for tests that need a logged-in user."""

    @pytest.fixture(autouse=True)
    def _setup_auth(self, authenticated_client: HTTPClient) -> None:
        self.client = authenticated_client


class BaseE2ETest(BaseTest):
    """Base for Playwright tests. Inherits BaseTest, adds page fixture."""

    page: "Page"

    @pytest.fixture(autouse=True)
    def _setup_page(self, page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")
```

## Fixtures Hierarchy (root conftest.py)

```python
# tests/conftest.py — session-scoped, shared across entire suite
import pytest
from tests.framework.config.settings import Settings
from tests.framework.clients.http_client import HTTPClient


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()  # pydantic BaseSettings, reads env


@pytest.fixture(scope="session")
def http_client(settings: Settings):
    client = HTTPClient(base_url=settings.BASE_URL)
    yield client
    client.close()


@pytest.fixture(scope="session")
def auth_token(http_client: HTTPClient, settings: Settings) -> str:
    from tests.api.clients.auth_client import AuthClient
    return AuthClient(http_client).login(settings.TEST_USER_EMAIL, settings.TEST_USER_PASSWORD)


@pytest.fixture
def authenticated_client(settings: Settings, auth_token: str):
    client = HTTPClient(base_url=settings.BASE_URL, token=auth_token)
    yield client
    client.close()
```

Module-level `conftest.py` inject service classes:

```python
# tests/api/test_users/conftest.py
import pytest
from tests.api.clients.users_client import UsersClient


@pytest.fixture
def users_client(http_client) -> UsersClient:
    return UsersClient(http_client)
```

## Settings (pydantic)

```python
# tests/framework/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.test", case_sensitive=True)

    BASE_URL: str = "http://localhost:8000"
    TEST_USER_EMAIL: str
    TEST_USER_PASSWORD: str
    FAKER_SEED: int = 42
    REQUEST_TIMEOUT_S: float = 10.0
```

## HTTPClient (thin httpx wrapper)

```python
# tests/framework/clients/http_client.py
import httpx


class HTTPClient(httpx.Client):
    def __init__(self, *, base_url: str, token: str | None = None, timeout: float = 10.0):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        super().__init__(base_url=base_url, headers=headers, timeout=timeout)
```

## Generated Config (pyproject.toml)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers --cov=src --cov-report=term --cov-fail-under=80 --alluredir=allure-results"
markers = [
    "smoke: Quick sanity checks",
    "regression: Full regression",
    "critical: Business-critical flows",
    "slow: Tests > 10s",
    "flaky: Known flaky (quarantined)",
]
```

## Smoke Test (OOP)

```python
# tests/test_smoke.py
import allure
import pytest

from tests.framework.base_test import BaseTest
from tests.framework.assertions import Assertions


@allure.feature("Health")
@pytest.mark.smoke
class TestSmoke(BaseTest):
    def test_app_responds_200(self):
        response = self.client.get("/health")
        Assertions.assert_status(response, 200)
```

## Framework Layout Emitted

```
tests/
├── conftest.py                     # session fixtures
├── framework/
│   ├── base_test.py                # BaseTest / BaseAuthenticatedTest / BaseE2ETest
│   ├── assertions.py               # Custom assertion helpers
│   ├── config/settings.py          # pydantic BaseSettings
│   └── clients/http_client.py      # httpx wrapper
├── api/                            # service-layer tests
└── test_smoke.py                   # one passing OOP test
```

## Framework Detection

| Dep in project | Adjustment |
|----------------|------------|
| `flask` | `app` + `client` session fixtures via Flask app factory |
| `django` | `DJANGO_SETTINGS_MODULE` + `db` fixture (pytest-django) |
| `fastapi` | `async_client = httpx.AsyncClient(transport=ASGITransport(app))`, `asyncio_mode = "auto"` |
| generic | no web fixture — just HTTP client |

## Common Pitfalls

- Never write `def test_...` at module level — always class-based.
- Don't pass config via env var reads in test bodies — use `self.settings`.
- Session-scoped fixtures must be thread-safe for `pytest-xdist`.
- Cleanup belongs in fixture `yield` teardown, never test body.

## Related Skills

- `pytest-oop-patterns` (python-stack) — the full pattern reference.
- `api-test-generator` — adds `BaseAPIClient` + Pydantic response models.
- `playwright-bootstrap` — adds `BasePage` + `BaseE2ETest`.
- `test-data-factory` — adds `DataGenerator` classes.
- `allure-reporting` — adds `@allure.step` conventions and Assertions helpers.
