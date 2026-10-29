"""Toast — transient notification component (assert visible with expected text)."""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import expect

from tests.base.base_components.base_component import BaseComponent


class Toast(BaseComponent):
    """Page-level ``[role='status']`` / ``[role='alert']`` notification."""

    _TOAST = "[role='status'], [role='alert']"

    @allure.step("Assert toast shows: {text}")
    def should_show(self, text: str) -> Self:
        toast = self.ctx.locator(self._TOAST)
        expect(toast).to_be_visible()
        expect(toast).to_contain_text(text)
        return self

    @allure.step("Assert no toast is visible")
    def should_not_show(self) -> Self:
        expect(self.ctx.locator(self._TOAST)).to_be_hidden()
        return self

    @allure.step("Wait for toast to dismiss")
    def wait_for_dismiss(self, timeout: float = 5000) -> Self:
        self.ctx.locator(self._TOAST).wait_for(state="hidden", timeout=timeout)
        return self
