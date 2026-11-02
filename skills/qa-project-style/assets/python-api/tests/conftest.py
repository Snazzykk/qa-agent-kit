from types import SimpleNamespace

import pytest

from configuration import get_base_url
from tests.controller_method.demo_item import DemoItemApi
from tests.helpers.demo_item_helper import fixture_create_and_delete_demo_item


@pytest.fixture(scope="session")
def api():
    """Replace demo_item with the current product's resource clients when its contract is known."""
    try:
        base_url = get_base_url()
    except ValueError as error:
        pytest.skip(str(error))
    client = DemoItemApi(base_url)
    yield SimpleNamespace(demo_item=client)
    client.close()
