"""Only this educational suite uses an in-memory adapter, never a real target."""
import json
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from requests.adapters import BaseAdapter

from tests.controller_method.demo_item import DemoItemApi


class DemoAdapter(BaseAdapter):
    def __init__(self):
        self.items = {}
        self.operations = []

    def send(self, request, **kwargs):
        path = urlsplit(request.url).path
        method = request.method
        self.operations.append(method)
        payload = None
        status = 404
        if path == "/demo/items" and method == "POST":
            body = json.loads(request.body)
            if isinstance(body.get("name"), str) and body["name"]:
                payload = {"id": uuid4().hex, "name": body["name"]}
                self.items[payload["id"]] = payload
                status = 201
            else:
                payload, status = {"detail": "name is required"}, 422
        elif path == "/demo/items" and method == "GET":
            payload, status = list(self.items.values()), 200
        elif path.startswith("/demo/items/"):
            item_id = path.rsplit("/", 1)[1]
            if item_id in self.items:
                if method == "GET":
                    payload, status = self.items[item_id], 200
                elif method == "DELETE":
                    del self.items[item_id]
                    status = 204
        response = requests.Response()
        response.status_code = status
        response.request = request
        response.url = request.url
        response.headers["Content-Type"] = "application/json"
        response._content = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return response

    def close(self):
        pass


@pytest.fixture
def api(request):
    adapter = DemoAdapter()
    session = requests.Session()
    session.trust_env = False
    session.mount("https://demo.invalid/", adapter)
    client = DemoItemApi("https://demo.invalid", session=session)
    yield SimpleNamespace(demo_item=client)
    client.close()
    assert not adapter.items, "The yield fixture must clean up every created demo item"
    if "create_and_delete_demo_item" in request.fixturenames:
        assert "DELETE" in adapter.operations, "The smoke test must exercise cleanup"
