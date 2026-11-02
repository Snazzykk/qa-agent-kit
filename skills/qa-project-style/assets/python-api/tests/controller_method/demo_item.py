"""Educational endpoints served only by the bundled fake adapter; not a product contract."""
from tests.core.http_client import HttpClient
from tests.models.model import DemoItemCreateSchema, DemoItemResponseSchema


class DemoItemApi(HttpClient):
    def create_demo_item_dto(self, dto: DemoItemCreateSchema):
        return self._send_request("POST", "/demo/items", "Создать учебный объект", json=dto,
                                  expected_model=DemoItemResponseSchema)

    def create_demo_item_raw(self, data: dict):
        return self._send_request("POST", "/demo/items", "Создать объект с raw-данными", json=data)

    def get_demo_item(self, item_id: str):
        return self._send_request("GET", f"/demo/items/{item_id}", "Получить учебный объект",
                                  expected_model=DemoItemResponseSchema)

    def get_list_demo_items(self):
        return self._send_request("GET", "/demo/items", "Получить список учебных объектов",
                                  expected_model=list[DemoItemResponseSchema])

    def delete_demo_item(self, item_id: str):
        return self._send_request("DELETE", f"/demo/items/{item_id}", "Удалить учебный объект")
