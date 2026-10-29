"""Sidebar navigation component — composed onto BasePage, never inherited."""
from __future__ import annotations

from typing import Self

import allure
from playwright.sync_api import Page

from tests.base.base_components.base_component import BaseComponent


class Sidebar(BaseComponent):
    """Left-hand navigation menu."""

    _DASHBOARD = "a[data-testid='nav-dashboard']"
    _SETTINGS = "a[data-testid='nav-settings']"
    _PROFILE = "a[data-testid='nav-profile']"
    _LOGOUT = "button[data-testid='nav-logout']"

    def __init__(self, page: Page) -> None:
        super().__init__(page, root=None)

    @allure.step("Navigate: Dashboard")
    def go_to_dashboard(self) -> Self:
        self.page.click(self._DASHBOARD)
        self.page.wait_for_load_state("networkidle")
        return self

    @allure.step("Navigate: Settings")
    def go_to_settings(self) -> Self:
        self.page.click(self._SETTINGS)
        self.page.wait_for_load_state("networkidle")
        return self

    @allure.step("Navigate: Profile")
    def go_to_profile(self) -> Self:
        self.page.click(self._PROFILE)
        self.page.wait_for_load_state("networkidle")
        return self

    @allure.step("Logout")
    def logout(self) -> Self:
        self.page.click(self._LOGOUT)
        self.page.wait_for_load_state("networkidle")
        return self
