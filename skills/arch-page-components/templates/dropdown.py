"""Dropdown — generic single-select dropdown (trigger + option list)."""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import expect

from tests.base.base_components.base_component import BaseComponent


class Dropdown(BaseComponent):
    """Click trigger → pick option by role + name.

    Options are looked up via ``ctx`` (page) because they often render
    in a portal outside the trigger's DOM tree.
    """

    @allure.step("Open dropdown")
    def open(self) -> Self:
        self.root.click()
        return self

    @allure.step("Select dropdown option: {option}")
    def select(self, option: str) -> Self:
        self.root.click()
        self.ctx.get_by_role("option", name=option).click()
        return self

    @allure.step("Assert dropdown has selected: {expected}")
    def should_have_selected(self, expected: str) -> Self:
        expect(self.root).to_contain_text(expected)
        return self
