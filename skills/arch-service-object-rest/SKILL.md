---
name: arch-service-object-rest
description: Scaffold a REST Service Object Model when the user explicitly selects SOM/Heisenbug architecture or the repository already uses it.
---

# Architecture Scaffold — REST Service Object Model

Select this architecture only for an explicit SOM request or an existing matching project. Preserve
that project's actual conventions. For other existing repositories or the default new Python API
blueprint, use `qa-project-style`; its resource-client layout does not require this SOM tree.

One-shot scaffold of the Service Object Model used by **ServiceObjectModelAdvanced / Heisenbug / VinobridgeUI**: a central `RequestClient` with session / logging / validation, `BaseAPI` as the shared parent, and one `services/<resource>/` folder per resource with `api.py`, `endpoints.py`, `payloads.py`, `models/`.

## When to Activate

- New API test suite.
- User says "SOM", "service object model", "scaffold api framework", "build rest client layer", "Heisenbug pattern".
- Prerequisite for `api-test-generator` (that skill fills per-resource content using this scaffold).

## Emitted Tree

```
tests/
├── client/
│   ├── __init__.py
│   └── api_client.py                 # RequestClient (httpx Session wrapper)
├── config/
│   ├── __init__.py
│   ├── base_api.py                   # BaseAPI — shared client/helper instance
│   ├── base_test.py                  # BaseTest + BaseAuthenticatedTest
│   ├── headers.py                    # Headers class (bearer/basic/api-key)
│   ├── settings.py                   # pydantic BaseSettings
│   └── tokens.py                     # Tokens helper (refresh, cache)
├── helpers/
│   └── helper.py                     # Helper (Allure attach, JSON logging)
├── services/
│   └── <resource>/                   # filled by api-test-generator
│       ├── api.py
│       ├── endpoints.py
│       ├── payloads.py
│       └── models/
├── utils/
│   └── logger.py                     # loguru / stdlib wrapper
└── conftest.py
```

## RequestClient (core)

```python
# tests/client/api_client.py
from __future__ import annotations
from typing import Type, TypeVar, Any

import allure
import httpx
from pydantic import BaseModel

from tests.config.headers import Headers
from tests.helpers.helper import Helper
from tests.utils.logger import logger

T = TypeVar("T", bound=BaseModel)


class RequestClient:
    """Central HTTP client used by every Service Object.

    - httpx.Client session (keeps connection pool warm)
    - Default headers merged with per-request overrides
    - Allure evidence on every call: a runnable curl, the request, the response
    - Pydantic response validation with status-code assertion
    - `success=True` asserts 2xx; `success=False` asserts 4xx/5xx
    """

    def __init__(self, base_url: str, headers: dict | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.helper = Helper()
        self.session = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.session.headers.update(Headers().get())
        if headers:
            self.session.headers.update(headers)

    # ---------------- evidence ----------------
    def _log_request(self, request: httpx.Request) -> None:
        logger.info(f"➡️  {request.method} {request.url}")
        self.helper.attach_request(request)          # curl + the request

    def _log_response(self, response: httpx.Response) -> None:
        logger.info(f"⬅️  {response.status_code} in {response.elapsed.total_seconds():.2f}s")
        self.helper.attach_response(response)        # status, timing, headers, body

    # ---------------- core request ----------------
    def _request(self, method: str, endpoint: str, *, headers=None, success=True, **kw) -> httpx.Response:
        # Build first, send second: the evidence is the REAL request
        # (session headers merged, params encoded, body serialised), and
        # it is attached BEFORE the send — so a call that never gets an
        # answer still leaves its curl behind.
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
    def get(self, model, endpoint, params=None, headers=None, success=True):
        resp = self._request("get", endpoint, params=params, headers=headers, success=success)
        return self._validate(resp, model) if success else resp

    def post(self, model, endpoint, json=None, headers=None, success=True, status=201):
        resp = self._request("post", endpoint, json=json, headers=headers, success=success)
        return self._validate(resp, model, status=status) if success else resp

    def patch(self, model, endpoint, json=None, headers=None, success=True):
        resp = self._request("patch", endpoint, json=json, headers=headers, success=success)
        return self._validate(resp, model) if success else resp

    def put(self, model, endpoint, json=None, headers=None, success=True):
        resp = self._request("put", endpoint, json=json, headers=headers, success=success)
        return self._validate(resp, model) if success else resp

    def delete(self, endpoint, headers=None, success=True, status=204):
        resp = self._request("delete", endpoint, headers=headers, success=success)
        assert resp.status_code == status, resp.text
        return resp
```

## BaseAPI (shared client instance)

```python
# tests/config/base_api.py
import os

from tests.client.api_client import RequestClient
from tests.helpers.helper import Helper


class BaseAPI:
    """Shared parent for every concrete API service.

    A single RequestClient instance is reused across all subclasses —
    session pooling + shared default headers.
    """

    client: RequestClient = RequestClient(base_url=os.environ["BASE_URL"])
    helper: Helper = Helper()
```

## Headers (auth strategies)

```python
# tests/config/headers.py
from __future__ import annotations


class Headers:
    def __init__(self, token: str | None = None, auth_type: str = "bearer", api_key: str | None = None):
        self.token = token
        self.auth_type = auth_type
        self.api_key = api_key

    def get(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token and self.auth_type == "bearer":
            h["Authorization"] = f"Bearer {self.token}"
        elif self.token and self.auth_type == "basic":
            h["Authorization"] = f"Basic {self.token}"
        elif self.api_key:
            h["X-API-Key"] = self.api_key
        return h
```

## Helper (Allure attachments + JSON pretty print)

```python
# tests/helpers/helper.py
import json
import allure


class Helper:
    """See templates/helper.py — this is the shape, that file is the source.

    Every API call leaves three attachments, in this order:
      curl · POST /users        a runnable reproduction of the request
      request · POST /users     method, URL, headers, body (as sent)
      response · 201 · 124 ms   status, timing, headers, body

    Secret headers (authorization, cookie, x-api-key, …) are redacted;
    ALLURE_SHOW_SECRETS=1 puts the real values back for local debugging.
    """

    @staticmethod
    def attach(name: str, data) -> None: ...
    @staticmethod
    def attach_request(request: httpx.Request) -> None: ...
    @staticmethod
    def attach_response(response: httpx.Response) -> None: ...
    @staticmethod
    def attach_transport_error(request: httpx.Request, exc: BaseException) -> None: ...
```

> **Evidence is not optional.** A failing API test whose report does not
> say what was sent and what came back costs an engineer the run. The
> curl is the headline: it is what a person pastes into a terminal to see
> the failure for themselves.

## Per-Resource Service (filled by `api-test-generator`)

```python
# tests/services/users/api.py
import allure

from tests.config.base_api import BaseAPI
from tests.config.headers import Headers
from tests.services.users.endpoints import Endpoints
from tests.services.users.payloads import Payloads
from tests.services.users.models.user import UserResponseModel
from tests.services.users.models.user_list import UserListResponseModel


class UsersAPI(BaseAPI):
    def __init__(self, token: str | None = None, auth_type: str = "bearer") -> None:
        self.headers = Headers(token=token, auth_type=auth_type)
        self.endpoints = Endpoints()
        self.payloads = Payloads()

    @allure.step("Get list of users (offset={offset}, limit={limit})")
    def list_users(self, offset: int = 0, limit: int = 10, success: bool = True):
        return self.client.get(
            model=UserListResponseModel,
            endpoint=self.endpoints.list_users,
            params={"offset": offset, "limit": limit},
            headers=self.headers.get(),
            success=success,
        )

    @allure.step("Create user")
    def create_user(self, payload=None, success: bool = True) -> UserResponseModel:
        return self.client.post(
            model=UserResponseModel,
            endpoint=self.endpoints.create_user,
            json=payload or Payloads.create_user(),
            headers=self.headers.get(),
            success=success,
        )

    @allure.step("Delete user {user_id}")
    def delete_user(self, user_id: int, success: bool = True):
        return self.client.delete(
            endpoint=self.endpoints.user_by_id(user_id),
            headers=self.headers.get(),
            success=success,
        )
```

```python
# tests/services/users/endpoints.py
class Endpoints:
    list_users = "/users"
    create_user = "/users"
    user_by_id = lambda self, user_id: f"/users/{user_id}"


# tests/services/users/payloads.py
from faker import Faker

faker = Faker()


class Payloads:
    @staticmethod
    def create_user(**overrides) -> dict:
        data = {
            "email": faker.email(),
            "password": faker.password(length=16),
            "name": faker.name(),
            "nickname": faker.user_name(),
        }
        data.update(overrides)
        return data

    @staticmethod
    def create_user_invalid_email() -> dict:
        return Payloads.create_user(email="not-an-email")
```

## OOP Test Using SOM

```python
@allure.feature("Users")
class TestCreateUser(BaseTest):
    @pytest.fixture(autouse=True)
    def _setup(self, auth_token: str):
        self.users = UsersAPI(token=auth_token)

    @pytest.mark.smoke
    def test_create_returns_201(self):
        user = self.users.create_user()
        assert user.email
```

## Common Pitfalls

- `BaseAPI.client` is a class attribute — one session for all services. Don't instantiate per-test (defeats pooling).
- `success=True` asserts 2xx inside `_request`; don't double-assert in the service method.
- Pydantic models go in `models/` per resource — don't stuff everything into one file.
- `endpoints.py` uses lambdas for path params; keep static paths as simple class attrs.

## Related Skills

- `api-test-generator` — fills `services/<resource>/` from OpenAPI/Postman/curl.
- `arch-service-object-graphql` — same pattern for GraphQL.
- `arch-service-object-grpc` — same pattern for gRPC stubs.
- `pytest-bootstrap` — provides `BaseTest` (works alongside `BaseAPI`).
- `mock-server-generator` — pair for offline runs.
