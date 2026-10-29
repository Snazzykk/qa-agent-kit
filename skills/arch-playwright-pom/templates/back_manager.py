"""BackManager — tracks navigation history so tests can assert Back/Forward flows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

import allure
from playwright.sync_api import Page


@dataclass(slots=True)
class BackManager:
    """URL-stack history tracker attached to a Playwright ``Page``.

    Push the current URL before each navigation and use ``go_back`` to
    return to the previous entry while keeping the stack in sync.
    """

    page: Page
    _stack: list[str] = field(default_factory=list)

    @allure.step("Push URL to history stack")
    def push(self) -> Self:
        self._stack.append(self.page.url)
        return self

    @allure.step("Pop URL from history stack")
    def pop(self) -> str | None:
        return self._stack.pop() if self._stack else None

    @property
    def current(self) -> str | None:
        return self._stack[-1] if self._stack else None

    @property
    def depth(self) -> int:
        return len(self._stack)

    @allure.step("Go back via browser (and pop stack)")
    def go_back(self) -> Self:
        self.page.go_back()
        self.pop()
        return self

    @allure.step("Clear navigation history")
    def clear(self) -> Self:
        self._stack.clear()
        return self
