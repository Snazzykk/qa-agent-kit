from uuid import uuid4

import allure
import pytest

from tests.helpers.allure_helper.allure_assertion import assert_true
from tests.models.model import DemoItemCreateSchema


def prepare_demo_item_body_dto(name: str | None = None) -> DemoItemCreateSchema:
    with allure.step("Подготовить данные учебного объекта"):
        return DemoItemCreateSchema(name=name if name is not None else f"Auto_test_item_{uuid4().hex}")


@pytest.fixture(scope="function", name="create_and_delete_demo_item")
def fixture_create_and_delete_demo_item(api):
    response = api.demo_item.create_demo_item_dto(prepare_demo_item_body_dto())
    assert_true(response.status_code == 201, "Код создания 201")
    item = response.model
    try:
        yield item
    finally:
        deleted = api.demo_item.delete_demo_item(item.id)
        assert_true(deleted.status_code == 204, "Код удаления 204")
