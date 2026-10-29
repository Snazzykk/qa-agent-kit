---
name: arch-playwright-pom
description: Scaffold a COMPLETE Playwright POM architecture from scratch in one call — BasePage with fluent Self-return API, BaseComponent hierarchy, Element/PageHelper wrappers, BackManager, Sidebar component, metaclasses for locator/url resolution, BaseTest, conftest, Allure wiring, urls.py. Activate when the user says "scaffold playwright framework", "build pom architecture", "full playwright project", "studio pattern", or starts a Playwright suite from zero.
---

# Architecture Scaffold — Playwright POM (Studio pattern)

**One call → full framework.** Produces the architecture used by the Studio reference project: fluent `Self` return types, component composition via `sidebar` / `back_manager` / `helper`, `@allure.step` everywhere, element wrappers, URL constants class, metaclass-based locator conversion.

## When to Activate

- Fresh project with no test framework.
- User says "build a POM framework", "scaffold Playwright", "full project architecture", "studio pattern".
- Before `page-object-generator` (that skill fills in concrete pages; this one lays the foundation).

## Emitted Tree (Studio-style)

```
tests/
├── base/
│   ├── __init__.py
│   ├── base_page.py                  # BasePage (fluent Self API)
│   ├── base_test.py                  # BaseTest / BaseAuthenticatedTest
│   └── base_components/
│       ├── __init__.py
│       ├── base_component.py         # BaseComponent
│       ├── sidebar.py                # Sidebar navigation component
│       ├── header.py                 # Header component
│       ├── modal.py                  # Modal dialog component
│       └── toast.py                  # Toast/notification component
├── pages/
│   ├── __init__.py
│   └── (empty — filled by page-object-generator)
├── utils/
│   ├── __init__.py
│   ├── element.py                    # Element wrapper + PageHelper
│   ├── back_manager.py               # Navigation state tracker
│   └── helpers.py                    # Misc helpers
├── metaclasses/
│   ├── __init__.py
│   ├── meta_locator.py               # auto-convert str → locator tuple
│   ├── meta_url_prefix.py            # prepend BASE_URL to _PAGE_URL
│   └── meta_combined.py              # CombinedMeta(URLPrefixMeta, MetaLocator)
├── data/
│   ├── __init__.py
│   └── urls.py                       # Urls class with route constants
├── config/
│   └── settings.py                   # pydantic BaseSettings
├── fixtures/
│   ├── __init__.py
│   ├── auth.py                       # logged_in_page / auth_token
│   └── pages.py                      # page-class fixtures
└── conftest.py                       # session-level plumbing
```

## BasePage (fluent Self pattern)

```python
# tests/base/base_page.py
from __future__ import annotations
import re
from typing import Self

import allure
from playwright.sync_api import Page, Locator, expect

from tests.base.base_components.sidebar import Sidebar
from tests.base.base_components.header import Header
from tests.base.base_components.toast import Toast
from tests.utils.element import PageHelper, Element
from tests.utils.back_manager import BackManager


class BasePage:
    """Root of the POM hierarchy.

    Fluent API: every action returns ``Self`` so tests can chain.
    Components (sidebar, header, toast) are composed, not inherited.
    """

    _PAGE_URL: str = ""  # relative path; metaclass prepends BASE_URL

    def __init__(self, page: Page) -> None:
        self.page = page
        self.expect = expect
        self.sidebar = Sidebar(page)
        self.header = Header(page)
        self.toast = Toast(page)
        self.back_manager = BackManager(page)
        self._helper = PageHelper(page)

    # ---------------- Navigation ----------------

    @allure.step("Open page: {self._PAGE_URL}")
    def open(self) -> Self:
        self.page.goto(self._PAGE_URL)
        self.page.wait_for_load_state("networkidle")
        self.screenshot()
        return self

    @allure.step("Assert page is opened")
    def is_opened(self) -> Self:
        self.page.wait_for_url(self._PAGE_URL)
        self.page.wait_for_load_state("networkidle")
        self.screenshot()
        return self

    @allure.step("Reload page")
    def reload(self) -> Self:
        self.page.reload()
        return self

    @allure.step("Go back")
    def go_back(self) -> Self:
        self.page.go_back()
        return self

    # ---------------- Element finders ----------------

    @property
    def helper(self) -> PageHelper:
        return self._helper

    def find(self, selector: str) -> Element: return self.helper.find(selector)
    def find_by_text(self, text: str, exact: bool = False) -> Element: return self.helper.find_by_text(text, exact)
    def find_by_role(self, role: str, **kw) -> Element: return self.helper.find_by_role(role, **kw)
    def find_by_test_id(self, tid: str) -> Element: return self.helper.find_by_test_id(tid)
    def find_by_label(self, label: str) -> Element: return self.helper.find_by_label(label)
    def find_by_placeholder(self, ph: str) -> Element: return self.helper.find_by_placeholder(ph)

    # ---------------- Screenshots ----------------

    @allure.step("Take screenshot")
    def screenshot(self, name: str = "screenshot") -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:
            pass
        self.page.wait_for_timeout(150)  # animation settle
        allure.attach(
            self.page.screenshot(full_page=True),
            name=name,
            attachment_type=allure.attachment_type.PNG,
        )

    # ---------------- Assertions ----------------

    def should_have_url(self, url: str, timeout: float | None = None) -> Self:
        expect(self.page).to_have_url(url, timeout=timeout)
        return self

    def should_have_url_containing(self, text: str, timeout: float | None = None) -> Self:
        expect(self.page).to_have_url(re.compile(f".*{re.escape(text)}.*"), timeout=timeout)
        return self

    def should_have_title(self, title: str, timeout: float | None = None) -> Self:
        expect(self.page).to_have_title(title, timeout=timeout)
        return self
```

## BaseComponent + Sidebar example

```python
# tests/base/base_components/base_component.py
from playwright.sync_api import Page, Locator


class BaseComponent:
    """Base for every reusable widget. Components accept either Page or Locator root."""

    def __init__(self, page: Page, root: Locator | None = None) -> None:
        self.page = page
        self.root = root or page.locator("body")


# tests/base/base_components/sidebar.py
import allure
from playwright.sync_api import Page

from tests.base.base_components.base_component import BaseComponent


class Sidebar(BaseComponent):
    """Sidebar navigation. Composed onto BasePage, never inherited from it."""

    _DASHBOARD = "a[data-testid='nav-dashboard']"
    _SETTINGS = "a[data-testid='nav-settings']"
    _LOGOUT = "button[data-testid='nav-logout']"

    @allure.step("Navigate: Dashboard")
    def go_to_dashboard(self) -> "Sidebar":
        self.page.click(self._DASHBOARD)
        return self

    @allure.step("Navigate: Settings")
    def go_to_settings(self) -> "Sidebar":
        self.page.click(self._SETTINGS)
        return self

    @allure.step("Logout")
    def logout(self) -> "Sidebar":
        self.page.click(self._LOGOUT)
        return self
```

## Element + PageHelper wrappers

```python
# tests/utils/element.py
from __future__ import annotations

import allure
from playwright.sync_api import Page, Locator, expect


class Element:
    """Thin wrapper around a Playwright Locator with Allure-annotated actions
    and fluent-style interface."""

    def __init__(self, locator: Locator, description: str = "") -> None:
        self.locator = locator
        self.description = description

    @allure.step("Click {self.description}")
    def click(self) -> "Element":
        self.locator.click()
        return self

    @allure.step("Fill {self.description}: {value}")
    def fill(self, value: str) -> "Element":
        self.locator.fill(value)
        return self

    @allure.step("Type {self.description}: {value}")
    def type(self, value: str, delay: float = 50) -> "Element":
        self.locator.type(value, delay=delay)
        return self

    @allure.step("Assert {self.description} is visible")
    def should_be_visible(self) -> "Element":
        expect(self.locator).to_be_visible()
        return self

    @allure.step("Assert {self.description} has text: {text}")
    def should_have_text(self, text: str) -> "Element":
        expect(self.locator).to_have_text(text)
        return self


class PageHelper:
    """Factory for Element objects with the right locator strategy."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def find(self, selector: str) -> Element:
        return Element(self.page.locator(selector), description=selector)

    def find_by_text(self, text: str, exact: bool = False) -> Element:
        return Element(self.page.get_by_text(text, exact=exact), description=f"text='{text}'")

    def find_by_role(self, role: str, **kw) -> Element:
        return Element(self.page.get_by_role(role, **kw), description=f"role='{role}'")

    def find_by_test_id(self, tid: str) -> Element:
        return Element(self.page.get_by_test_id(tid), description=f"test-id='{tid}'")

    def find_by_label(self, label: str) -> Element:
        return Element(self.page.get_by_label(label), description=f"label='{label}'")

    def find_by_placeholder(self, ph: str) -> Element:
        return Element(self.page.get_by_placeholder(ph), description=f"placeholder='{ph}'")
```

## Metaclasses (auto-convert string → locator, prepend base URL)

```python
# tests/metaclasses/meta_locator.py
class MetaLocator(type):
    """Auto-convert string class attrs into locators based on prefix."""

    def __new__(cls, name, bases, attrs):
        for key, value in attrs.items():
            if not (isinstance(value, str) and key.startswith("_") and not key.startswith("__")):
                continue
            if value.startswith("//"):
                attrs[key] = ("xpath", value)
            elif value.startswith(("#", ".")):
                attrs[key] = ("css", value)
        return super().__new__(cls, name, bases, attrs)


# tests/metaclasses/meta_url_prefix.py
import os


class URLPrefixMeta(type):
    """Prepend BASE_URL env var to every `_PAGE_URL` on subclasses."""

    def __new__(cls, name, bases, attrs):
        base = os.environ.get("BASE_URL", "")
        url = attrs.get("_PAGE_URL")
        if url and not url.startswith(("http://", "https://")):
            attrs["_PAGE_URL"] = f"{base.rstrip('/')}{url}"
        return super().__new__(cls, name, bases, attrs)


# tests/metaclasses/meta_combined.py
from .meta_locator import MetaLocator
from .meta_url_prefix import URLPrefixMeta


class CombinedMeta(URLPrefixMeta, MetaLocator):
    pass
```

## BaseTest + conftest

```python
# tests/base/base_test.py
import pytest
import allure
import httpx
from playwright.sync_api import Page


class BaseTest:
    page: Page

    @pytest.fixture(autouse=True)
    def _setup(self, page: Page):
        self.page = page
        yield
        if hasattr(self, "_final_screenshot"):
            allure.attach(self.page.screenshot(), name="final",
                          attachment_type=allure.attachment_type.PNG)


class BaseAuthenticatedTest(BaseTest):
    @pytest.fixture(autouse=True)
    def _auth(self, logged_in_page: Page):
        self.page = logged_in_page


class BaseE2ETest(BaseAuthenticatedTest):
    """For UI tests with API-driven preconditions. See `templates/base_e2e_test.py`."""
    api: httpx.Client

    @pytest.fixture(autouse=True)
    def _api_and_state(self, api_client: httpx.Client):
        self.api = api_client
        self.setup_state()
        yield
        self.teardown_state()

    def setup_state(self) -> None:
        """Override — API-only preconditions. NEVER click."""

    def teardown_state(self) -> None:
        """Override — API-only cleanup."""
```

## UI economy rule (don't click twice) — first-class architectural rule

> **A UI test verifies UI behavior. State setup, auth, data seeding — that all goes through the API.**
> If a UI flow already has its own dedicated test, every other test that needs that state must reach
> it via the API. **Do not click the same button twice.**

### The classic mistake

The product has two flows: **create classified ad** and **delete classified ad**. Both are valid UI tests.

```python
# ✅ test_create_ad — full UI flow IS the subject. Long, expensive, but necessary.
def test_user_can_publish_ad(self):
    NewAdPage(self.page) \
        .fill_title("iPhone 15") \
        .fill_description(...) \
        .upload_photos([...]) \
        .pick_category("Electronics") \
        .click_publish()
    expect(self.page.get_by_role("status")).to_have_text("Published")
```

```python
# ❌ test_delete_ad — anti-pattern: clicks through the entire create flow again
def test_user_can_delete_ad(self):
    # 5+ seconds of clicking, NOT what this test exists to verify:
    self.page.goto("/login"); self.page.fill(...); self.page.click(...)
    self.page.goto("/ads/new"); self.page.fill(...); self.page.upload(...)
    self.page.click("publish")
    # …finally:
    self.page.goto("/ads/me"); self.page.click("[data-testid=delete]")
    expect(self.page.get_by_role("status")).to_have_text("Deleted")
```

```python
# ✅ test_delete_ad — done right: precondition via API, UI only for the action under test
class TestDeleteAd(BaseE2ETest):
    def setup_state(self) -> None:
        self.ad = self.api.post("/api/ads", json={
            "title": "iPhone 15", "category_id": 7, "price": 800,
        }).json()  # ← 50ms instead of 5 seconds, no flake from upload widget

    def test_owner_can_delete_their_ad(self) -> None:
        self.page.goto(f"/ads/{self.ad['id']}")
        AdPage(self.page).click_delete().confirm()
        expect(self.page.get_by_role("status")).to_have_text("Deleted")

    def teardown_state(self) -> None:
        # If the delete failed, scrub via API. If it succeeded, this is a no-op (404).
        self.api.delete(f"/api/ads/{self.ad['id']}")
```

### What's actually being tested?

| Test | UI scope (what it owns) | Precondition (via API) |
|---|---|---|
| `test_create_ad` | New-ad form, photo upload, validation, publish flow | logged-in user |
| `test_delete_ad` | Delete button, confirm modal, post-delete UI state | user + existing ad |
| `test_edit_ad`   | Edit form, save flow | user + existing ad |
| `test_browse_ads` | List render, filters, pagination | user + 50 seeded ads |

**Each UI test owns one UI surface.** Everything else is a precondition that goes through `self.api`.

### The required layered architecture

This rule is only practical when the project has the right layers — which is exactly what
the scaffolds emit:

| Layer | Where it lives | Owns |
|---|---|---|
| **UI layer** | `tests/pages/` (POM via `arch-playwright-pom` / `arch-page-components`) | Selectors, page actions, assertions on rendered DOM |
| **API helpers** | `services/<resource>/api.py` (via `arch-service-object-rest` / `-graphql` / `-grpc`) | Data preconditions: create/seed/advance state |
| **Utilities** | `tests/framework/` (via `pytest-bootstrap`) | Auth tokens, role factories, env config, fixture composition |

`BaseE2ETest` (above) wires all three: `self.page` (UI), `self.api` (httpx client), session storage
auto-injected from an API-minted token.

### Pyramid budget

UI tests are the slowest, flakiest, most expensive tier. Spend them on flows that only a real
browser can verify (visual outcome, keyboard nav, browser-specific behavior). Target distribution
audited by `project-audit`:

```
unit          ~65%   pure functions, validators, calculators
integration   ~25%   handler + DB / Kafka / external API
ui            ~10%   only flows where the UI itself is the subject
```

If your UI tier is >20%, you're almost certainly clicking twice. Run `e2e-test-suite-refactor`
to find the duplication.

## Usage After Scaffold

```python
# tests/pages/login_page.py (emitted by page-object-generator)
import allure
from typing import Self
from tests.base.base_page import BasePage
from tests.metaclasses.meta_combined import CombinedMeta


class LoginPage(BasePage, metaclass=CombinedMeta):
    _PAGE_URL = "/login"
    _LOGIN_INPUT = "//input[@id='login']"         # → ("xpath", "//input[@id='login']")
    _PASSWORD_INPUT = "//input[@id='password']"
    _SUBMIT = "#submit"                            # → ("css", "#submit")

    @allure.step("Login as {username}")
    def login(self, username: str, password: str) -> Self:
        self.page.fill(self._LOGIN_INPUT[1], username)
        self.page.fill(self._PASSWORD_INPUT[1], password)
        self.page.click(self._SUBMIT[1])
        self.page.wait_for_load_state("networkidle")
        self.screenshot()
        return self
```

## Common Pitfalls

- Metaclass `__new__` must call `super().__new__`, never `type.__new__` directly — breaks multiple-inheritance.
- `_PAGE_URL` with full http URL skips prefix injection; keep relative in source.
- Components take the `Page` (not `Page` + root) unless they're instance-scoped widgets — see `BaseComponent` dual-mode init.
- Never mutate class attrs after class creation; metaclass runs once at import.

## Related Skills

- `page-object-generator` — fills `tests/pages/` after this scaffold.
- `arch-page-components` — extends the `base_components/` library.
- `arch-service-object-rest` — pairs with this for API + UI coverage.
- `source-aware-test-gen` — emits tests grounded in SUT source.
