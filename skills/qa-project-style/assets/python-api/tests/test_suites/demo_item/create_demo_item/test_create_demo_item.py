"""Educational transport smoke; the fake API contract is not a real product specification."""
import allure

from tests.helpers.allure_helper.allure_assertion import assert_contains, assert_equals_txt, assert_true


@allure.title("Учебный объект создаётся, читается и присутствует в списке")
def test_created_demo_item_is_available(api, create_and_delete_demo_item):
    item = create_and_delete_demo_item

    with allure.step("Получить созданный объект"):
        response = api.demo_item.get_demo_item(item.id)
        assert_true(response.status_code == 200, "Код получения 200")
        assert_equals_txt(item.name, response.model.name, "Имя объекта сохраняется")

    with allure.step("Проверить объект в списке"):
        response_list = api.demo_item.get_list_demo_items()
        assert_true(response_list.status_code == 200, "Код списка 200")
        assert_contains([value.id for value in response_list.model], item.id, "Объект присутствует в списке")
