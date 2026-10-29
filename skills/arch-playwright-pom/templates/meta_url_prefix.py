"""URLPrefixMeta — prepends ``BASE_URL`` env var to every ``_PAGE_URL`` on subclasses.

Skips prefix injection when ``_PAGE_URL`` is absolute (starts with http:// or https://).
"""
from __future__ import annotations

import os


class URLPrefixMeta(type):
    """Metaclass that rewrites ``_PAGE_URL`` to absolute form."""

    def __new__(mcls, name: str, bases: tuple, attrs: dict) -> type:
        base = os.environ.get("BASE_URL", "")
        url = attrs.get("_PAGE_URL")
        if url and isinstance(url, str) and not url.startswith(("http://", "https://")):
            attrs["_PAGE_URL"] = f"{base.rstrip('/')}{url}"
        return super().__new__(mcls, name, bases, attrs)
