"""BaseComponent — parent for every reusable Playwright widget.

Components accept either Page (page-level widget like Toast) or a scoped
Locator root (container-bound widget like Table).
"""
from __future__ import annotations

from playwright.sync_api import Locator, Page


class BaseComponent:
    """Base for every reusable widget.

    :param page: the Playwright ``Page`` (always required — used for
        cross-component dispatch like option menus attached to ``body``).
    :param root: optional ``Locator`` scoping the widget. If omitted the
        component operates at page level (e.g. ``Toast``, ``Modal``).
    """

    def __init__(self, page: Page, root: Locator | None = None) -> None:
        self.page = page
        self.root = root if root is not None else page.locator("body")

    def _scoped(self, selector: str) -> Locator:
        """Return a locator scoped under ``self.root``."""
        return self.root.locator(selector)
