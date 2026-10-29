"""RequestClient — the central httpx-backed HTTP client for every Service Object.

- ``httpx.Client`` session (keeps connection pool warm across tests)
- Default headers merged with per-request overrides
- Allure evidence on EVERY call: a runnable ``curl``, the request as it
  went on the wire, and the response with status, timing and headers
- Pydantic response validation with status-code assertion
- ``success=True`` asserts 2xx/3xx; ``success=False`` asserts 4xx/5xx
"""
from __future__ import annotations

from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel

from tests.config.headers import Headers
from tests.helpers.helper import Helper
from tests.utils.logger import logger

T = TypeVar("T", bound=BaseModel)


class RequestClient:
    """Session-pooled HTTP client used by every service."""

    def __init__(self, base_url: str, headers: dict | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.helper = Helper()
        self.session = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.session.headers.update(Headers().get())
        if headers:
            self.session.headers.update(headers)

    # ---------------- evidence ----------------
    def _log_request(self, request: httpx.Request) -> None:
        logger.info(f"-> {request.method} {request.url}")
        self.helper.attach_request(request)

    def _log_response(self, response: httpx.Response) -> None:
        logger.info(
            f"<- {response.status_code} in {response.elapsed.total_seconds():.2f}s"
        )
        self.helper.attach_response(response)

    # ---------------- core request ----------------
    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        headers: dict | None = None,
        success: bool = True,
        **kw: Any,
    ) -> httpx.Response:
        # Built first, sent second: the evidence is the REAL request —
        # session headers merged, params encoded, body serialised — and
        # it is attached before the send, so a call that never gets an
        # answer still leaves its curl in the report.
        request = self.session.build_request(method, endpoint, headers=headers, **kw)
        self._log_request(request)
        try:
            response = self.session.send(request)
        except httpx.HTTPError as exc:
            self.helper.attach_transport_error(request, exc)
            raise
        self._log_response(response)
        if success is True:
            assert 200 <= response.status_code < 400, response.text
        elif success is False:
            assert response.status_code >= 400, response.text
        return response

    def _validate(self, response: httpx.Response, model: Type[T], status: int = 200) -> T | list[T]:
        assert response.status_code == status, response.text
        data = response.json()
        if isinstance(data, list):
            return [model(**item) for item in data]
        return model(**data)

    # ---------------- HTTP verbs ----------------
    def get(
        self,
        model: Type[T],
        endpoint: str,
        params: dict | None = None,
        headers: dict | None = None,
        success: bool = True,
    ) -> T | list[T] | httpx.Response:
        resp = self._request("get", endpoint, params=params, headers=headers, success=success)
        return self._validate(resp, model) if success else resp

    def post(
        self,
        model: Type[T],
        endpoint: str,
        json: dict | None = None,
        headers: dict | None = None,
        success: bool = True,
        status: int = 201,
    ) -> T | list[T] | httpx.Response:
        resp = self._request("post", endpoint, json=json, headers=headers, success=success)
        return self._validate(resp, model, status=status) if success else resp

    def patch(
        self,
        model: Type[T],
        endpoint: str,
        json: dict | None = None,
        headers: dict | None = None,
        success: bool = True,
    ) -> T | list[T] | httpx.Response:
        resp = self._request("patch", endpoint, json=json, headers=headers, success=success)
        return self._validate(resp, model) if success else resp

    def put(
        self,
        model: Type[T],
        endpoint: str,
        json: dict | None = None,
        headers: dict | None = None,
        success: bool = True,
    ) -> T | list[T] | httpx.Response:
        resp = self._request("put", endpoint, json=json, headers=headers, success=success)
        return self._validate(resp, model) if success else resp

    def delete(
        self,
        endpoint: str,
        headers: dict | None = None,
        success: bool = True,
        status: int = 204,
    ) -> httpx.Response:
        resp = self._request("delete", endpoint, headers=headers, success=success)
        if success:
            assert resp.status_code == status, resp.text
        return resp
