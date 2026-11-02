from typing import Any, Generic, TypeVar

from requests import Response


T = TypeVar("T")


class ApiResponse(Generic[T]):
    def __init__(self, response: Response, model: T | None = None):
        self.raw_response = response
        self._model = model

    @property
    def status_code(self) -> int:
        return self.raw_response.status_code

    @property
    def json(self) -> Any:
        return self.raw_response.json()

    @property
    def model(self) -> T:
        if self._model is None:
            raise ValueError("This response has no validated model")
        return self._model
