"""Navbar — top navigation bar component."""
from __future__ import annotations

from typing import Self

import allure

from tests.base.base_components.base_component import BaseComponent


class Navbar(BaseComponent):
    """Top-level primary navigation (horizontal)."""

    _SECTION_LINK_TMPL = "a[data-section='{section}']"

    @allure.step("Navigate to section: {section}")
    def go_to(self, section: str) -> Self:
        selector = self._SECTION_LINK_TMPL.format(section=section)
        if self.root is not None:
            self.root.locator(selector).click()
        else:
            self.ctx.locator(selector).click()
        return self

    @allure.step("Click user menu")
    def open_user_menu(self) -> Self:
        (self.root or self.ctx).get_by_role("button", name="User menu").click()
        return self
