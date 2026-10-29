"""Form — generic form component with fill(dict) + submit + field-error assertion."""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import expect

from tests.base.base_components.base_component import BaseComponent


class Form(BaseComponent):
    """Fills fields by label text, submits, asserts per-field errors."""

    _SUBMIT = "button[type='submit']"
    _RESET = "button[type='reset']"

    @allure.step("Fill form: {fields}")
    def fill(self, fields: dict[str, str]) -> Self:
        for label, value in fields.items():
            self.root.get_by_label(label).fill(value)
        return self

    @allure.step("Submit form")
    def submit(self) -> Self:
        self.root.locator(self._SUBMIT).click()
        return self

    @allure.step("Reset form")
    def reset(self) -> Self:
        self.root.locator(self._RESET).click()
        return self

    @allure.step("Assert field error for: {label}")
    def should_have_error_for(self, label: str) -> Self:
        error = self.root.locator(f"[aria-describedby*='{label}']")
        expect(error).to_be_visible()
        return self

    @allure.step("Assert submit is disabled")
    def should_have_submit_disabled(self) -> Self:
        expect(self.root.locator(self._SUBMIT)).to_be_disabled()
        return self
