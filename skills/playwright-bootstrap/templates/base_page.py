"""Base Page Object — every page class inherits this."""

from __future__ import annotations

import allure
from playwright.sync_api import Page, expect


class BasePage:
    """Base class for all Page Objects."""

    url_path: str = "/"

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.url_path}"

    @allure.step("Open {self.url}")
    def open(self) -> None:
        self.page.goto(self.url)
        self.page.wait_for_load_state("networkidle")

    @allure.step("Assert page title is {title}")
    def assert_title(self, title: str) -> None:
        expect(self.page).to_have_title(title)

    def attach_screenshot(self, name: str = "screenshot") -> None:
        allure.attach(
            self.page.screenshot(full_page=True),
            name=name,
            attachment_type=allure.attachment_type.PNG,
        )
