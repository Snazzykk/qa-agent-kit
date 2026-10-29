"""CombinedMeta — stack URLPrefixMeta on top of MetaLocator.

Every concrete Page subclass uses ``metaclass=CombinedMeta`` to get both
locator-tuple rewriting and BASE_URL prefix injection.
"""
from __future__ import annotations

from tests.metaclasses.meta_locator import MetaLocator
from tests.metaclasses.meta_url_prefix import URLPrefixMeta


class CombinedMeta(URLPrefixMeta, MetaLocator):
    """Ordered MRO: URL prefix first, locator rewrite second."""

    pass
