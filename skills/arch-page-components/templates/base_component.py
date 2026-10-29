"""BaseComponent — dual-stack base for Playwright ``Locator`` or Selenium ``WebElement`` roots."""
from __future__ import annotations

from typing import Any


class BaseComponent:
    """Base for every reusable component.

    :param page_or_driver: ``Page`` (Playwright) or ``WebDriver`` (Selenium).
    :param root: optional scoped root (``Locator`` or ``WebElement``).
        When ``None`` the component operates at page level.
    :param description: human-readable label shown in Allure steps.
    """

    def __init__(
        self,
        page_or_driver: Any,
        root: Any = None,
        *,
        description: str = "",
    ) -> None:
        self.ctx = page_or_driver
        self.root = root
        self.description = description or self.__class__.__name__

    def _scoped(self, selector: str) -> Any:
        """Return a locator scoped under ``self.root`` (or ``ctx`` if no root)."""
        if self.root is not None and hasattr(self.root, "locator"):
            return self.root.locator(selector)
        if self.root is not None and hasattr(self.root, "find_element"):
            from selenium.webdriver.common.by import By

            return self.root.find_element(By.CSS_SELECTOR, selector)
        if hasattr(self.ctx, "locator"):
            return self.ctx.locator(selector)
        raise RuntimeError("No locator strategy available for this component root.")
