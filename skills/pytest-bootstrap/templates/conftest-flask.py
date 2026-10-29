"""conftest-flask.py — template for Flask projects."""

from __future__ import annotations

import pytest
from flask import Flask

# Adjust this import to your app factory
from app import create_app  # type: ignore


@pytest.fixture(scope="session")
def app() -> Flask:
    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with application.app_context():
        # Initialize schema, seed data, etc.
        yield application


@pytest.fixture
def client(app: Flask):
    return app.test_client()


@pytest.fixture
def runner(app: Flask):
    return app.test_cli_runner()
