import allure


def assert_true(condition: bool, message: str = "") -> None:
    with allure.step(message or "Проверить условие"):
        assert condition, message


def assert_equals_txt(expected: object, actual: object, message: str = "") -> None:
    with allure.step(message or "Сравнить значения"):
        assert str(actual) == str(expected), message or f"{actual!r} != {expected!r}"


def assert_contains(container, expected, message: str = "") -> None:
    with allure.step(message or "Проверить вхождение"):
        assert expected in container, message or f"{expected!r} is absent"
