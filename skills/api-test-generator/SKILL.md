---
name: api-test-generator
description: Generate OOP pytest API tests from OpenAPI / Postman / curl — BaseAPIClient service layer, Pydantic request+response models, BaseTest inheritance, Allure steps, DataGenerator factories, custom Assertions. Activate when the user says "generate api tests", "tests from openapi", "curl to pytest", or provides a Swagger URL / Postman JSON / curl snippet.
---

# API Test Generator — OOP

Generates an OOP pytest suite from any API spec. Strict patterns: **service layer, Pydantic models, BaseTest inheritance, factory data, Allure steps on every call.**

## Input Modes

1. OpenAPI URL or `openapi.json/yaml`
2. Postman collection `.json`
3. `curl` command (single or multi-line)

## Emitted Structure

```
tests/
├── api/
│   ├── clients/              # service layer
│   │   ├── base_api_client.py
│   │   ├── users_client.py
│   │   └── pets_client.py
│   ├── models/               # Pydantic request + response
│   │   ├── user.py
│   │   └── pet.py
│   ├── factories/            # DataGenerator per resource
│   │   └── user_factory.py
│   └── test_users.py         # BaseTest subclasses, parametrized
├── framework/
│   ├── base_test.py
│   ├── assertions.py
│   ├── clients/http_client.py
│   └── config/settings.py
└── conftest.py
```

## BaseAPIClient Pattern

```python
# tests/api/clients/base_api_client.py
from __future__ import annotations

import allure
import httpx

from tests.framework.clients.http_client import HTTPClient


class BaseAPIClient:
    """Service-layer base. All endpoint clients inherit this."""

    ENDPOINT: str = ""

    def __init__(self, client: HTTPClient):
        self.client = client

    def _url(self, path: str = "") -> str:
        return f"{self.ENDPOINT}{path}"
```

## Concrete Client (per resource/tag)

```python
# tests/api/clients/users_client.py
import allure
import httpx

from tests.api.clients.base_api_client import BaseAPIClient
from tests.api.models.user import CreateUserRequest, UpdateUserRequest


class UsersClient(BaseAPIClient):
    ENDPOINT = "/api/v1/users"

    @allure.step("POST /users — Create user: {data.email}")
    def create(self, data: CreateUserRequest) -> httpx.Response:
        return self.client.post(self._url(), json=data.model_dump(mode="json"))

    @allure.step("GET /users/{user_id}")
    def get(self, user_id: int) -> httpx.Response:
        return self.client.get(self._url(f"/{user_id}"))

    @allure.step("GET /users — List (page={page})")
    def list(self, page: int = 1, per_page: int = 20) -> httpx.Response:
        return self.client.get(self._url(), params={"page": page, "per_page": per_page})

    @allure.step("PATCH /users/{user_id}")
    def update(self, user_id: int, data: UpdateUserRequest) -> httpx.Response:
        return self.client.patch(self._url(f"/{user_id}"), json=data.model_dump(mode="json", exclude_unset=True))

    @allure.step("DELETE /users/{user_id}")
    def delete(self, user_id: int) -> httpx.Response:
        return self.client.delete(self._url(f"/{user_id}"))
```

## Pydantic Models

```python
# tests/api/models/user.py
from pydantic import BaseModel, EmailStr, Field


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=12)


class UpdateUserRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    name: str
    is_active: bool
    created_at: str


class ErrorResponse(BaseModel):
    detail: str | list[dict]
```

## DataGenerator (factory)

```python
# tests/api/factories/user_factory.py
from faker import Faker

from tests.api.models.user import CreateUserRequest

fake = Faker()


class UserDataGenerator:
    """Factory for user request payloads."""

    @classmethod
    def create_user(cls, **overrides) -> CreateUserRequest:
        data = {
            "email": fake.unique.email(),
            "name": fake.name(),
            "password": fake.password(length=16),
        }
        data.update(overrides)
        return CreateUserRequest(**data)
```

## Custom Assertions

```python
# tests/framework/assertions.py
from typing import TypeVar

import allure
import httpx

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Assertions:
    @staticmethod
    @allure.step("Assert status is {expected}")
    def assert_status(response: httpx.Response, expected: int) -> None:
        assert response.status_code == expected, (
            f"Expected {expected}, got {response.status_code}. Body: {response.text[:200]}"
        )

    @staticmethod
    @allure.step("Validate response against {model.__name__}")
    def assert_schema(response: httpx.Response, model: type[T]) -> T:
        return model.model_validate(response.json())

    @staticmethod
    @allure.step("Assert error detail contains: {expected_detail}")
    def assert_error(response: httpx.Response, status: int, expected_detail: str | None = None) -> None:
        assert response.status_code == status
        if expected_detail:
            body = response.json()
            text = body.get("detail") if isinstance(body, dict) else str(body)
            assert expected_detail in str(text)
```

## OOP Test Class

```python
# tests/api/test_users.py
import allure
import pytest

from tests.framework.base_test import BaseTest, BaseAuthenticatedTest
from tests.framework.assertions import Assertions
from tests.api.clients.users_client import UsersClient
from tests.api.factories.user_factory import UserDataGenerator
from tests.api.models.user import UserResponse


@allure.feature("Users")
class TestCreateUser(BaseAuthenticatedTest):
    """POST /users scenarios."""

    @pytest.fixture(autouse=True)
    def _setup_client(self, authenticated_client):
        self.users = UsersClient(authenticated_client)

    @pytest.mark.smoke
    @allure.story("Happy path")
    def test_create_user_returns_201(self):
        data = UserDataGenerator.create_user()
        response = self.users.create(data)
        Assertions.assert_status(response, 201)
        body = Assertions.assert_schema(response, UserResponse)
        assert body.email == data.email

    @pytest.mark.parametrize("field,value,error_field", [
        ("email", "not-email", "email"),
        ("name", "", "name"),
        ("password", "short", "password"),
    ], ids=["invalid-email", "empty-name", "short-password"])
    @allure.story("Field validation")
    def test_create_user_validation(self, field: str, value: str, error_field: str):
        data = UserDataGenerator.create_user(**{field: value})
        response = self.users.create(data)
        Assertions.assert_error(response, 422, error_field)


@allure.feature("Users")
class TestListUsers(BaseAuthenticatedTest):
    @pytest.fixture(autouse=True)
    def _setup_client(self, authenticated_client):
        self.users = UsersClient(authenticated_client)

    @pytest.mark.smoke
    def test_list_returns_200_and_paginated(self):
        response = self.users.list(page=1, per_page=10)
        Assertions.assert_status(response, 200)
        data = response.json()
        assert len(data["items"]) <= 10
```

## Status-Code Authorization Matrix

```python
@allure.feature("Authorization")
class TestUserAuthorization(BaseTest):
    """Unauthenticated access across resources."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("GET", "/api/v1/users/1"),
        ("DELETE", "/api/v1/users/1"),
    ], ids=["list", "create", "get", "delete"])
    def test_returns_401_without_token(self, method: str, path: str):
        response = getattr(self.client, method.lower())(path)
        Assertions.assert_status(response, 401)
```

## Per-Input-Mode Behavior

| Input | Mapping |
|-------|---------|
| OpenAPI tag → one client class | `Pet` tag → `PetsClient(BaseAPIClient)` |
| OpenAPI schema → one Pydantic model | `#/components/schemas/Pet` → `Pet(BaseModel)` |
| `oneOf` / `anyOf` | Pydantic `Union` with discriminator |
| `security: bearerAuth` | generates `authenticated_client` usage, reads `API_TOKEN` env |
| Postman folder | one client class per folder; collection auth → auth fixture |
| curl | one test class with one method; auth header → env var |

## Common Pitfalls

- Never embed secrets from curl/HAR into tests — always env var.
- Don't generate per-test clients; use fixtures to inject.
- `oneOf` → Union with discriminator, not first branch.
- Multipart/binary → emit a TODO comment, don't hallucinate file paths.

## Related Skills

- `pytest-bootstrap` — prerequisite, defines `BaseTest` hierarchy.
- `test-data-factory` — richer `DataGenerator` with sub-factories and traits.
- `mock-server-generator` — fake server for offline runs against same spec.
- `contract-testing` — promote to consumer-driven contracts later.
- `har-to-test` — alternative input.
