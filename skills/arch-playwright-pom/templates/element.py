"""Element — thin, Allure-annotated wrapper around a Playwright Locator.

``PageHelper`` is a factory that returns Element instances using the right
locator strategy (selector / role / text / test-id / label / placeholder).
"""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import Locator, Page, expect


class Element:
    """Fluent wrapper around a Playwright ``Locator``."""

    def __init__(self, locator: Locator, description: str = "") -> None:
        self.locator = locator
        self.description = description or "element"

    @allure.step("Click {self.description}")
    def click(self) -> Self:
        self.locator.click()
        return self

    @allure.step("Double-click {self.description}")
    def dblclick(self) -> Self:
        self.locator.dblclick()
        return self

    @allure.step("Hover {self.description}")
    def hover(self) -> Self:
        self.locator.hover()
        return self

    @allure.step("Fill {self.description}: {value}")
    def fill(self, value: str) -> Self:
        self.locator.fill(value)
        return self

    @allure.step("Type {self.description}: {value}")
    def type(self, value: str, delay: float = 50) -> Self:
        self.locator.type(value, delay=delay)
        return self

    @allure.step("Assert {self.description} is visible")
    def should_be_visible(self) -> Self:
        expect(self.locator).to_be_visible()
        return self

    @allure.step("Assert {self.description} is hidden")
    def should_be_hidden(self) -> Self:
        expect(self.locator).to_be_hidden()
        return self

    @allure.step("Assert {self.description} has text: {text}")
    def should_have_text(self, text: str) -> Self:
        expect(self.locator).to_have_text(text)
        return self

    @allure.step("Assert {self.description} contains text: {text}")
    def should_contain_text(self, text: str) -> Self:
        expect(self.locator).to_contain_text(text)
        return self

    @allure.step("Assert {self.description} has value: {value}")
    def should_have_value(self, value: str) -> Self:
        expect(self.locator).to_have_value(value)
        return self


class PageHelper:
    """Factory for ``Element`` objects using the full Playwright strategy set."""

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
