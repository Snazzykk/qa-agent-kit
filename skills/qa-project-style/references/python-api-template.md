# Python API template

Самодостаточный нейтральный образец для **новых Python API QA-проектов без готовых тестов**.
Идентификатор blueprint: `python-api-template`. Рабочий пример лежит в `../assets/python-api/`;
внешний репозиторий и доступ к коду прежних проектов для использования не требуются.

## Что перенимать

| Соглашение | Файл в `assets/python-api/` |
|---|---|
| Тесты — функции pytest; предметные шаги и проверки на русском | `tests/test_suites/demo_item/create_demo_item/test_create_demo_item.py` |
| Папки по ресурсу и операции: `tests/test_suites/<resource>/<operation>/test_*.py` | `tests/test_suites/demo_item/create_demo_item/test_create_demo_item_raw.py` |
| `api` собирает клиентов ресурсов в `SimpleNamespace` | `tests/conftest.py` |
| Клиент ресурса наследует общий `HttpClient`; DTO для корректных данных, raw-dict для негативных | `tests/controller_method/demo_item.py` |
| HTTP-вызов централизован; DTO сериализуется, ответ проверяется моделью | `tests/core/http_client.py` |
| `ApiResponse` предоставляет `status_code`, `json`, `model`, raw response | `tests/core/api_response.py` |
| Pydantic-модели вынесены в `tests/models/` | `tests/models/model.py` |
| Подготовка и cleanup принадлежат helpers/yield-фикстурам | `tests/helpers/demo_item_helper.py` |
| Assertions вызываются через функции с Allure-шагами | `tests/helpers/allure_helper/allure_assertion.py` |
| Содержательные названия Allure, идентификаторы кейсов только из реальных источников | `tests/test_suites/demo_item/create_demo_item/test_create_demo_item.py` |

Идентификаторы TestIT/TMS и ссылки добавляются, когда их дал пользователь или вернул реальный источник.
Без них используй содержательный Allure title, не создавай фиктивные номера и корпоративные URL.

## Границы переноса

Существующий проект сохраняет собственную архитектуру. Этот образец задаёт личное предпочтение
пользователя при отсутствии тестового фундамента; он не требует `BaseTest`, обязательных классов,
дополнительной сервисной прослойки или одной универсальной структуры для всех стеков.

Контракты API, права, схемы и ожидаемые статусы определяются требованиями текущего продукта.
Ожидания учебного fake API не являются правилами для новых прикладных тестов.

## Свойства переносимого каркаса

- Проверка TLS включена по умолчанию; у запросов есть timeout.
- Ошибка схемы успешного ответа поднимает `ValidationError`. Список проверяется как `list[ResponseSchema]`.
- Assertions сравнивают значения явно и сохраняют регистр. Типы и `None` не подменяются проверкой
  truthiness.
- Fixtures проверяют результат cleanup, HTTP-сессия закрывается. Рабочий стенд не зашит в конфигурацию.
- В лог и Allure попадают название действия и статус; полные тела, credentials и корпоративные адреса
  в учебные данные не включаются.

## Минимальный переносимый пример

```text
configuration.py
pytest.ini
requirements.txt
tests/
  conftest.py                         # api для явно заданного QA_BASE_URL
  core/{http_client,api_response}.py
  controller_method/demo_item.py      # DTO/raw методы учебного ресурса
  models/model.py
  helpers/demo_item_helper.py         # данные и yield cleanup
  helpers/allure_helper/allure_assertion.py
  test_suites/demo_item/create_demo_item/
    conftest.py                       # fake adapter, локальный override api
    test_create_demo_item.py          # офлайн smoke
    test_create_demo_item_raw.py      # негативный raw-кейс без создания данных
```

Файлы `demo_item` — работающий учебный пример. Он помогает проверить связанность каркаса без
доступа к продукту. Первая прикладная фича должна получить собственные требования, кейсы и
соответствующие им клиенты, модели и тесты.
