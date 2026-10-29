"""Table — generic Playwright table component (headers / rows / cells / sort / filter)."""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import Locator, expect

from tests.base.base_components.base_component import BaseComponent


class Table(BaseComponent):
    """Reusable table widget — works on any ``<table>`` or ARIA grid container."""

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

    @allure.step("Filter table: {query}")
    def filter(self, query: str) -> Self:
        self.root.get_by_placeholder("Filter").fill(query)
        return self
