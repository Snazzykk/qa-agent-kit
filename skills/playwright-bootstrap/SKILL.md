---
name: playwright-bootstrap
description: Initialize Playwright for Python with OOP patterns — BasePage / BaseComponent hierarchy, BaseE2ETest class, pytest-playwright config, screenshot-on-failure, and one OOP smoke test. Activate when the user says "set up playwright", "add browser tests", "playwright config", "e2e tests".
---

# Playwright Bootstrap — OOP

Sets up Playwright-for-Python with strict OOP: **every page is a class, every test is a method on a class, selectors live on the Page Object, never in tests.**

## When to Activate

- Project has no `tests/e2e/` or no Playwright deps.
- After `pytest-bootstrap` (depends on `BaseE2ETest`).
- Before `page-object-generator`, `visual-regression`, `accessibility-a11y`.

## BasePage Hierarchy

```python
# tests/e2e/pages/base_page.py
from __future__ import annotations

import allure
from playwright.sync_api import Page, Locator, expect


class BasePage:
    """Root of the POM hierarchy. Every page class inherits this."""

    url_path: str = "/"

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.url_path}"

    @allure.step("Open {self.url}")
    def open(self) -> None:
        self.page.goto(self.url)
        self.page.wait_for_load_state("networkidle")

    @allure.step("Assert page title is {title}")
    def assert_title(self, title: str) -> None:
        expect(self.page).to_have_title(title)

    @allure.step("Attach screenshot")
    def attach_screenshot(self, name: str = "screenshot") -> None:
        allure.attach(
            self.page.screenshot(full_page=True),
            name=name,
            attachment_type=allure.attachment_type.PNG,
        )


class BaseAuthenticatedPage(BasePage):
    """Base for pages behind auth. Uses logged_in_page fixture."""

    def assert_logged_in(self) -> None:
        expect(self.page.get_by_test_id("user-menu")).to_be_visible()


class BaseComponent:
    """Shared widget/component (navbar, modal, toast)."""

    def __init__(self, root: Locator):
        self.root = root
```

## UI economy rule (don't click twice)

**UI tests verify UI behavior. Everything else goes through the API.**

This is enforced by the conftest below: `logged_in_page` mints a session via the
auth API and injects the cookie — never clicks `/login`. For state setup
(creating users, seeding data, advancing state), inject `api_client` and call it
from `setup_method` / a fixture. Cleanup the same way.

```python
class TestEditProfile(BaseE2ETest):
    @pytest.fixture(autouse=True)
    def _state(self, api_client):
        # ✅ Setup via API — fast, no clicks
        self.user = api_client.post("/api/users", json={...}).json()
        yield
        # ✅ Cleanup via API
        api_client.delete(f"/api/users/{self.user['id']}")

    def test_user_can_edit_email(self):
        # The ONE UI flow this test exists to verify
        self.page.goto(f"/users/{self.user['id']}/edit")
        edit = EditProfilePage(self.page)
        edit.fill_email("new@x.test").save()
        edit.expect_toast("Profile updated")
```

❌ Anti-pattern: clicking through `/signup` to get a user, then clicking through
`/login`, then finally testing the actual flow. Burns 5+ seconds per test on
forms that have their own dedicated tests, and bleeds their flakiness into yours.

**Target pyramid:** `unit ~65% · integration ~25% · ui ~10%`. Spend UI tests
on flows that *only* a real browser can verify.

## BaseE2ETest

`BaseE2ETest` comes from `pytest-bootstrap`. Tests inherit it:

```python
# tests/e2e/test_login.py
import allure
import pytest

from tests.framework.base_test import BaseE2ETest
from tests.e2e.pages.login_page import LoginPage
from tests.e2e.pages.dashboard_page import DashboardPage


@allure.feature("Auth")
class TestLogin(BaseE2ETest):

    @pytest.fixture(autouse=True)
    def _setup_pages(self):
        self.login = LoginPage(self.page, self.base_url)
        self.dashboard = DashboardPage(self.page, self.base_url)

    @pytest.mark.smoke
    @allure.story("Valid credentials redirect to dashboard")
    def test_valid_login_redirects_to_dashboard(self):
        self.login.open()
        self.login.submit(email="user@example.com", password="P@ssw0rd1234")
        self.dashboard.assert_loaded()
```

## Concrete Page Object

```python
# tests/e2e/pages/login_page.py
import allure
from playwright.sync_api import expect

from tests.e2e.pages.base_page import BasePage


class LoginPage(BasePage):
    url_path = "/login"

    # Locators as instance attributes via @property — rebinds every access
    @property
    def email_input(self):
        return self.page.get_by_label("Email")

    @property
    def password_input(self):
        return self.page.get_by_label("Password")

    @property
    def submit_button(self):
        return self.page.get_by_role("button", name="Log in")

    @property
    def error_banner(self):
        return self.page.get_by_role("alert")

    @allure.step("Fill email: {email}")
    def fill_email(self, email: str) -> "LoginPage":
        self.email_input.fill(email)
        return self

    @allure.step("Fill password")
    def fill_password(self, password: str) -> "LoginPage":
        self.password_input.fill(password)
        return self

    @allure.step("Click Submit")
    def click_submit(self) -> None:
        self.submit_button.click()

    @allure.step("Submit login form for {email}")
    def submit(self, *, email: str, password: str) -> None:
        self.fill_email(email).fill_password(password).click_submit()

    @allure.step("Assert error: {message}")
    def assert_error(self, message: str) -> None:
        expect(self.error_banner).to_contain_text(message)
```

## conftest.py (e2e)

```python
# tests/e2e/conftest.py
import pytest
from playwright.sync_api import BrowserContext, Page

from tests.api.clients.auth_client import AuthClient
from tests.framework.clients.http_client import HTTPClient


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 800},
    }


@pytest.fixture
def logged_in_page(browser: BrowserContext, base_url: str, settings) -> Page:
    """E2E fixture: inject an auth cookie so tests skip the login UI."""
    api = AuthClient(HTTPClient(base_url=settings.BASE_URL))
    token = api.login(settings.TEST_USER_EMAIL, settings.TEST_USER_PASSWORD)

    context = browser.new_context()
    context.add_cookies([{
        "name": "session",
        "value": token,
        "domain": base_url.split("://")[1].split("/")[0],
        "path": "/",
    }])
    page = context.new_page()
    yield page
    context.close()
```

## pyproject.toml additions

```toml
[tool.pytest.ini_options]
addopts = "--browser chromium --screenshot only-on-failure --video retain-on-failure --tracing retain-on-failure"
```

## Parallel-Safety Rules

- Each test creates its own user/entities (no shared IDs).
- `scope="session"` fixtures must be read-only after creation.
- No module-level mutable state on Page Object classes.
- `pytest-xdist` default: `pytest -n auto`.

## Common Pitfalls

- Don't store locators as class attributes with `page.locator(...)` — evaluates at import time and fails. Use `@property` or construct in methods.
- Don't inherit `BasePage` AND expose raw `page.locator` in tests — tests go through methods, never touch `self.page` directly.
- Headed mode only in local dev; CI must stay headless for artifact capture.

## Related Skills

- `pytest-bootstrap` — prerequisite (defines `BaseE2ETest`).
- `page-object-generator` — generates concrete `Page` classes from URL/HTML.
- `playwright-codegen-enhancer` — refactors `codegen` output into OOP.
- `visual-regression`, `accessibility-a11y` — extend the e2e suite.
