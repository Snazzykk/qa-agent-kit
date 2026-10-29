"""BaseAPI — shared class-attribute RequestClient for every REST service.

A single ``RequestClient`` instance is reused across all subclasses so the
underlying httpx session pool stays warm.
"""
from __future__ import annotations

import os

from tests.client.api_client import RequestClient
from tests.helpers.helper import Helper


class BaseAPI:
    """Shared parent for every concrete API service."""

    client: RequestClient = RequestClient(base_url=os.environ.get("BASE_URL", "http://localhost:8000"))
    helper: Helper = Helper()
