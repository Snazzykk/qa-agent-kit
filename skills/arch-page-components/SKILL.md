---
name: arch-page-components
description: Scaffold a reusable Page Components library for Playwright OR Selenium — BaseComponent hierarchy, Form / Table / Modal / Toast / Navbar / Sidebar / DatePicker / Dropdown / Tabs / Pagination / FileUpload / Search / Breadcrumb / Alert, each as a composable class that accepts a root Locator and exposes Allure-annotated fluent methods. Activate when the user says "page components library", "reusable widgets", "component framework", "form / table / modal class".
---

# Architecture Scaffold — Page Components Library

Generates a library of reusable widget classes so pages compose instead of duplicating selectors. Works for both Playwright (`Locator`) and Selenium (`WebElement` + `By`). Component detected from deps.

## Emitted Layout

```
tests/base/base_components/
├── base_component.py             # BaseComponent (dual-stack)
├── form.py                       # Form (generic input/submit)
├── table.py                      # Table (rows, cells, sort, filter)
├── modal.py                      # Modal (dialog open/close)
├── toast.py                      # Toast (assert visible, wait for dismiss)
├── navbar.py                     # Navbar (top nav)
├── sidebar.py                    # Sidebar (side nav)
├── dropdown.py                   # Dropdown (select, multi-select)
├── datepicker.py                 # DatePicker
├── tabs.py                       # Tabs
├── pagination.py                 # Pagination
├── file_upload.py                # FileUpload
├── search.py                     # SearchBar
├── breadcrumb.py                 # Breadcrumb
└── alert.py                      # Alert / confirm dialog
```

## BaseComponent (dual-stack)

```python
# tests/base/base_components/base_component.py
from __future__ import annotations
from typing import Any

import allure


class BaseComponent:
    """Base for all components. `root` is a Locator (Playwright) or WebElement (Selenium).

    Subclasses declare _SELECTORS as class attrs; methods return Self for fluent chaining.
    """

    def __init__(self, page_or_driver: Any, root: Any = None, *, description: str = "") -> None:
        self.ctx = page_or_driver           # page or driver
        self.root = root                    # scoped Locator / WebElement or None = full page
        self.description = description or self.__class__.__name__

    def _scoped(self, selector: str):
        """Return a locator scoped under self.root, or page-level if no root."""
        if self.root is not None and hasattr(self.root, "locator"):
            return self.root.locator(selector)       # Playwright
        if self.root is not None and hasattr(self.root, "find_element"):
            from selenium.webdriver.common.by import By
            return self.root.find_element(By.CSS_SELECTOR, selector)
        return self.ctx.locator(selector) if hasattr(self.ctx, "locator") else None
```

## Table Component (Playwright)

```python
# tests/base/base_components/table.py
from __future__ import annotations
from typing import Self

import allure
from playwright.sync_api import Locator, expect

from tests.base.base_components.base_component import BaseComponent


class Table(BaseComponent):
    """Generic table component.

    Usage:
        orders_table = Table(page, page.get_by_test_id("orders-table"))
        orders_table.row_by_text("Order #42").click_action("Edit")
    """

    _HEADER = "thead th"
    _ROW = "tbody tr"
    _CELL = "td"

    def headers(self) -> list[str]:
        return [h.inner_text() for h in self.root.locator(self._HEADER).all()]

    def rows(self) -> list[Locator]:
        return self.root.locator(self._ROW).all()

    def row_by_text(self, text: str) -> Locator:
        return self.root.locator(f"{self._ROW}:has-text('{text}')")

    def cell(self, row_index: int, column: str) -> Locator:
        col_index = self.headers().index(column)
        return self.rows()[row_index].locator(self._CELL).nth(col_index)

    @allure.step("Assert table has {expected} rows")
    def should_have_rows(self, expected: int) -> Self:
        expect(self.root.locator(self._ROW)).to_have_count(expected)
        return self

    @allure.step("Assert row contains: {text}")
    def should_contain_row_with(self, text: str) -> Self:
        expect(self.root).to_contain_text(text)
        return self

    @allure.step("Sort by column: {column}")
    def sort_by(self, column: str) -> Self:
        self.root.get_by_role("columnheader", name=column).click()
        return self

    @allure.step("Filter: {query}")
    def filter(self, query: str) -> Self:
        self.root.get_by_placeholder("Filter").fill(query)
        return self
```

## Form Component

```python
# tests/base/base_components/form.py
from typing import Self
import allure

from tests.base.base_components.base_component import BaseComponent


class Form(BaseComponent):
    """Generic form wrapper. Fills fields by label → submits.

    Usage:
        Form(page, page.get_by_test_id("signup-form")).fill({
            "Email": "a@b.com",
            "Password": "P@ss1234",
        }).submit()
    """

    _SUBMIT = "button[type='submit']"

    @allure.step("Fill form: {fields}")
    def fill(self, fields: dict[str, str]) -> Self:
        for label, value in fields.items():
            self.root.get_by_label(label).fill(value)
        return self

    @allure.step("Submit form")
    def submit(self) -> Self:
        self.root.locator(self._SUBMIT).click()
        return self

    @allure.step("Assert field error: {label}")
    def should_have_error_for(self, label: str) -> Self:
        error = self.root.locator(f"[aria-describedby*='{label}']")
        error.wait_for(state="visible")
        return self
```

## Modal, Toast, Dropdown (sketch)

```python
# tests/base/base_components/modal.py
class Modal(BaseComponent):
    _DIALOG = "[role='dialog']"
    _CLOSE = "[aria-label='Close']"

    @allure.step("Assert modal is open")
    def should_be_open(self) -> Self:
        expect(self.ctx.locator(self._DIALOG)).to_be_visible()
        return self

    @allure.step("Close modal")
    def close(self) -> Self:
        self.ctx.locator(self._CLOSE).click()
        return self


# tests/base/base_components/toast.py
class Toast(BaseComponent):
    _TOAST = "[role='status']"

    @allure.step("Assert toast: {text}")
    def should_show(self, text: str) -> Self:
        toast = self.ctx.locator(self._TOAST)
        expect(toast).to_be_visible()
        expect(toast).to_contain_text(text)
        return self


# tests/base/base_components/dropdown.py
class Dropdown(BaseComponent):
    @allure.step("Select: {option}")
    def select(self, option: str) -> Self:
        self.root.click()
        self.ctx.get_by_role("option", name=option).click()
        return self
```

## Pages Composing Components

```python
class OrdersPage(BasePage):
    _PAGE_URL = "/orders"

    def __init__(self, page):
        super().__init__(page)
        self.table = Table(page, page.get_by_test_id("orders-table"))
        self.filter_form = Form(page, page.get_by_test_id("orders-filter"))
        self.create_modal = Modal(page, None)

    def create_order(self, data: dict) -> Self:
        self.find_by_role("button", name="New order").click()
        self.create_modal.should_be_open()
        Form(self.page, self.page.locator("form")).fill(data).submit()
        self.toast.should_show("Order created")
        return self
```

## Common Pitfalls

- Components take a `Locator` root (Playwright) or `WebElement` (Selenium) — never the raw page unless intentionally page-level.
- `Toast` / `Modal` often live outside the trigger's DOM tree; scope them to `ctx` (page), not to button root.
- Don't duplicate component logic on pages — always compose.
- Component selectors stay private (`_HEADER`); tests never touch them.

## Related Skills

- `arch-playwright-pom` / `arch-selenium-pom` — prerequisites.
- `page-object-generator` — uses components when generating pages.
