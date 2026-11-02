"""Negative checks for the educational in-memory API contract."""
import allure

from tests.helpers.allure_helper.allure_assertion import assert_equals_txt, assert_true


@allure.title("Учебный объект без имени не создаётся")
def test_create_demo_item_without_name(api):
    with allure.step("Отправить пустой JSON-объект"):
        response = api.demo_item.create_demo_item_raw({})
        assert_true(response.status_code == 422, "Код создания без имени 422")
        assert_equals_txt("name is required", response.json["detail"], "Причина отказа: имя обязательно")

    with allure.step("Проверить отсутствие созданных объектов"):
        response_list = api.demo_item.get_list_demo_items()
        assert_true(response_list.status_code == 200, "Код списка 200")
        assert_true(response_list.model == [], "Список объектов пуст")
