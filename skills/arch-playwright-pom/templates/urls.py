"""Urls — single source of truth for every route in the app.

Tests and page objects read route constants from here so changing a path
only touches one file.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Urls:
    """Route constants (relative paths — metaclass prepends BASE_URL)."""

    HOME: str = "/"
    LOGIN: str = "/login"
    LOGOUT: str = "/logout"
    SIGNUP: str = "/signup"
    DASHBOARD: str = "/dashboard"
    PROFILE: str = "/profile"
    SETTINGS: str = "/settings"
    ORDERS: str = "/orders"
    ORDER_DETAIL: str = "/orders/{order_id}"

    def order_detail(self, order_id: str) -> str:
        return self.ORDER_DETAIL.format(order_id=order_id)
