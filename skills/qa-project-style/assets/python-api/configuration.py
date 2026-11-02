"""The real target is explicit; the bundled demo overrides api with a fake transport."""
import os
from urllib.parse import urlsplit


def get_base_url() -> str:
    value = os.environ.get("QA_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise ValueError("Set QA_BASE_URL to the approved test environment before using the real api fixture")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("QA_BASE_URL must be an HTTP(S) URL without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("QA_BASE_URL must not contain a query or fragment")
    return value
