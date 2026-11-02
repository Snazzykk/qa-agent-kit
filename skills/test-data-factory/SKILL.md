---
name: test-data-factory
description: Build OOP factory-boy / Faker factories for SQLAlchemy / Django / Pydantic models — SQLAlchemyModelFactory / DjangoModelFactory subclasses with SubFactory, Trait, sequence, and post_generation hooks. Activate when the user says "test data factory", "factory-boy", "fake data", "factories for my models".
---

# Test Data Factory — OOP

For an existing repository, first inspect its data helpers and fixtures through `qa-project-style`.
Extend the existing approach when it covers the task. Use the factory-boy classes below when that
dependency and architecture are already chosen; the `python-api-template` blueprint uses helper functions.

Produces OOP `factory-boy` classes for every detected model. **Strict inheritance hierarchy, SubFactory for FKs, Trait for variants, post_generation hooks for M2M.**

## Base Class per ORM

```python
# tests/factories/base_factory.py
import factory
from faker import Faker

fake = Faker()
Faker.seed(42)  # deterministic


class BaseSQLAFactory(factory.alchemy.SQLAlchemyModelFactory):
    """Base for all SQLAlchemy factories. Session injected via conftest."""

    class Meta:
        abstract = True
        sqlalchemy_session_persistence = "commit"


class BaseDjangoFactory(factory.django.DjangoModelFactory):
    class Meta:
        abstract = True


class BasePydanticFactory(factory.Factory):
    """Base for Pydantic request/response payload factories."""

    class Meta:
        abstract = True
```

## Model Factory Example — SQLAlchemy

```python
# tests/factories/user_factory.py
import factory

from app.models import User, Post
from tests.factories.base_factory import BaseSQLAFactory, fake


class UserFactory(BaseSQLAFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Faker("name")
    is_active = True
    role = "user"

    class Params:
        inactive = factory.Trait(is_active=False)
        admin = factory.Trait(role="admin", is_staff=True)
        premium = factory.Trait(role="premium", is_subscribed=True)

    @factory.post_generation
    def groups(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        for group in extracted:
            self.groups.append(group)


class PostFactory(BaseSQLAFactory):
    class Meta:
        model = Post

    title = factory.Faker("sentence", nb_words=6)
    body = factory.Faker("paragraph", nb_sentences=5)
    author = factory.SubFactory(UserFactory)
    published_at = factory.Faker("date_time_between", start_date="-30d", end_date="now")
```

## Pydantic Request Payload Factory

```python
# tests/api/factories/user_factory.py
import factory

from tests.api.models.user import CreateUserRequest
from tests.factories.base_factory import BasePydanticFactory, fake


class CreateUserRequestFactory(BasePydanticFactory):
    class Meta:
        model = CreateUserRequest

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Faker("name")
    password = factory.LazyFunction(lambda: fake.password(length=16))
```

## Session Wiring (conftest.py)

```python
# tests/conftest.py (addition)
import pytest

from tests.factories.base_factory import BaseSQLAFactory


@pytest.fixture(autouse=True)
def _bind_factory_session(db_session):
    """Bind factories to the per-test SQLAlchemy session."""
    BaseSQLAFactory._meta.sqlalchemy_session = db_session


@pytest.fixture(autouse=True)
def _reset_sequences():
    """Avoid unique-constraint collisions across tests."""
    from tests.factories.user_factory import UserFactory
    UserFactory.reset_sequence(0)
```

## Usage in OOP Tests

```python
@allure.feature("Posts")
class TestListPosts(BaseAuthenticatedTest):
    @pytest.fixture(autouse=True)
    def _setup(self, authenticated_client, db_session):
        self.posts = PostsClient(authenticated_client)
        self.author = UserFactory(admin=True)
        self.published = PostFactory.create_batch(5, author=self.author)

    def test_list_returns_all_published(self):
        response = self.posts.list()
        Assertions.assert_status(response, 200)
        assert len(response.json()["items"]) == 5
```

## ORM → Factory Mapping

| Type / name hint | Faker provider |
|------------------|----------------|
| `email` | `"email"` with `Sequence` prefix for uniqueness |
| `first_name`, `last_name`, `name` | matching `Faker` |
| `str` / `VARCHAR` | `"word"` or `"sentence"` |
| `int` / `Integer` | `"pyint"` with range |
| `datetime` | `"date_time_between"` |
| `bool` | `"boolean"` |
| `JSON` | `"pydict"` |
| Enum / `choices` | `FuzzyChoice` |
| FK relationship | `SubFactory(OtherFactory)` |
| M2M relationship | `@factory.post_generation` |

## Common Pitfalls

- Session must be bound at fixture time, not at import — otherwise first import locks a session.
- Don't use `Faker("email")` without `Sequence` prefix — collisions flake.
- Circular FKs → use `post_generation` on one side, `SubFactory` on the other.
- Django `auto_now_add` fields: don't assign, let ORM set them.

## Related Skills

- `pytest-bootstrap` — prerequisite, defines fixture hierarchy.
- `api-test-generator` — consumes request factories.
- `synthetic-test-data-llm` — pair Faker for structure + LLM for realistic body text.
- `database-migrations` — keep factories in sync with schema.
