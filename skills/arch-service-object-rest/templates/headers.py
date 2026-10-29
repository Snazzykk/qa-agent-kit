"""Headers — assemble default headers with bearer / basic / api-key auth strategies."""
from __future__ import annotations


class Headers:
    """Build the header dict injected into every outbound request.

    :param token: bearer/basic credential value (no prefix).
    :param auth_type: ``"bearer"`` or ``"basic"``.
    :param api_key: alternative to token-based auth — sent as ``X-API-Key``.
    """

    def __init__(
        self,
        token: str | None = None,
        auth_type: str = "bearer",
        api_key: str | None = None,
    ) -> None:
        self.token = token
        self.auth_type = auth_type
        self.api_key = api_key

    def get(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token and self.auth_type == "bearer":
            h["Authorization"] = f"Bearer {self.token}"
        elif self.token and self.auth_type == "basic":
            h["Authorization"] = f"Basic {self.token}"
        elif self.api_key:
            h["X-API-Key"] = self.api_key
        return h
