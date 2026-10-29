"""Modal — dialog component (open/close + content assertion)."""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import expect

from tests.base.base_components.base_component import BaseComponent


class Modal(BaseComponent):
    """Wrap a ``[role='dialog']`` modal. Page-level scope (not bound to a trigger)."""

    _DIALOG = "[role='dialog']"
    _CLOSE = "[aria-label='Close']"
    _CONFIRM = "button[data-testid='modal-confirm']"
    _CANCEL = "button[data-testid='modal-cancel']"

    @allure.step("Assert modal is open")
    def should_be_open(self) -> Self:
        expect(self.ctx.locator(self._DIALOG)).to_be_visible()
        return self

    @allure.step("Assert modal is closed")
    def should_be_closed(self) -> Self:
        expect(self.ctx.locator(self._DIALOG)).to_be_hidden()
        return self

    @allure.step("Close modal")
    def close(self) -> Self:
        self.ctx.locator(self._CLOSE).click()
        return self

    @allure.step("Confirm modal")
    def confirm(self) -> Self:
        self.ctx.locator(self._CONFIRM).click()
        return self

    @allure.step("Cancel modal")
    def cancel(self) -> Self:
        self.ctx.locator(self._CANCEL).click()
        return self
