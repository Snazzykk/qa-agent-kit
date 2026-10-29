"""MetaLocator — converts private string attrs into locator tuples at class creation.

``_FOO = "//div"`` → ``("xpath", "//div")``
``_FOO = "#id"``   → ``("css",   "#id")``
``_FOO = ".cls"``  → ``("css",   ".cls")``

Non-matching strings and dunder attrs are left untouched.
"""
from __future__ import annotations


class MetaLocator(type):
    """Metaclass that rewrites string locator constants to tuples."""

    def __new__(mcls, name: str, bases: tuple, attrs: dict) -> type:
        for key, value in list(attrs.items()):
            if not isinstance(value, str):
                continue
            if not key.startswith("_") or key.startswith("__"):
                continue
            if value.startswith("//"):
                attrs[key] = ("xpath", value)
            elif value.startswith(("#", ".")):
                attrs[key] = ("css", value)
        return super().__new__(mcls, name, bases, attrs)
