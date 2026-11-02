from typing import Any
from urllib.parse import urlsplit

import allure
import requests
from pydantic import BaseModel, TypeAdapter

from tests.core.api_response import ApiResponse


class HttpClient:
    def __init__(self, base_url: str, session: requests.Session | None = None, timeout: float = 10):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("An explicit HTTP(S) base_url is required")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a base_url without credentials, query or fragment")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _send_request(self, method: str, path: str, step_title: str, expected_model: Any = None,
                      **kwargs: Any) -> ApiResponse:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("The resource path must start with one slash")
        if isinstance(kwargs.get("json"), BaseModel):
            kwargs["json"] = kwargs["json"].model_dump(by_alias=True, mode="json")
        with allure.step(step_title):
            response = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
            allure.attach(str(response.status_code), "Response status", allure.attachment_type.TEXT)
            model = None
            if expected_model is not None and 200 <= response.status_code < 300:
                model = TypeAdapter(expected_model).validate_python(response.json())
            return ApiResponse(response, model)

    def close(self) -> None:
        self.session.close()
