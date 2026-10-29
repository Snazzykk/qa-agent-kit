"""BasePage — root of the Playwright POM hierarchy (Studio pattern).

Fluent API: every action returns ``Self`` so tests can chain.
Components (sidebar, header, toast) are composed, not inherited.
"""
from __future__ import annotations

import re
from typing import Self

import allure
from playwright.sync_api import Page, expect

from tests.base.base_components.header import Header
from tests.base.base_components.sidebar import Sidebar
from tests.base.base_components.toast import Toast
from tests.utils.back_manager import BackManager
from tests.utils.element import Element, PageHelper


class BasePage:
    """Root of the POM hierarchy.

    Subclasses declare ``_PAGE_URL`` (relative) and private ``_SELECTOR``
    strings — the ``CombinedMeta`` metaclass prepends ``BASE_URL`` and
    converts ``//…`` / ``#…`` / ``.…`` into locator tuples automatically.
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

    def find(self, selector: str) -> Element:
        return self.helper.find(selector)

    def find_by_text(self, text: str, exact: bool = False) -> Element:
        return self.helper.find_by_text(text, exact)

    def find_by_role(self, role: str, **kw) -> Element:
        return self.helper.find_by_role(role, **kw)

    def find_by_test_id(self, tid: str) -> Element:
        return self.helper.find_by_test_id(tid)

    def find_by_label(self, label: str) -> Element:
        return self.helper.find_by_label(label)

    def find_by_placeholder(self, ph: str) -> Element:
        return self.helper.find_by_placeholder(ph)

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

    def should_contain_text(self, text: str) -> Self:
        expect(self.page.locator("body")).to_contain_text(text)
        return self
