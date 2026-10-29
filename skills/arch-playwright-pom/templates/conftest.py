"""Playwright POM conftest — API-driven setup, UI for verification only.

UI ECONOMY RULE
---------------
UI tests verify *UI behavior*. Everything else (creating users, seeding data,
authenticating, putting the system in a target state) goes through the API.

Why:
  - Faster: API call is ~50ms; clicking through signup is ~3-5s.
  - More reliable: the form you don't care about can't flake your test.
  - Honest: when this test fails, you know it's THIS UI flow that broke,
    not signup or login bleeding into the failure.

Pattern:
  1. setup via API     → seed users, set state, mint a session token
  2. inject storage_state into the browser context
  3. navigate to the page under test
  4. perform the ONE UI interaction this test exists to verify
  5. assert UI outcome

`logged_in_page` below mints an auth cookie via API + inject — no /login click.
For state seeding, depend on `api_client` and call it inside your test.
"""
from __future__ import annotations

import os
from typing import Iterator

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


# --------------------------------------------------------------------------- #
# Core browser plumbing                                                        #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:3000").rstrip("/")


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=os.environ.get("HEADLESS", "1") == "1")
        yield browser
        browser.close()


# --------------------------------------------------------------------------- #
# API client — used for setup, NOT for assertion                              #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def api_client(api_base_url: str) -> Iterator[httpx.Client]:
    """Session-scoped httpx.Client for backend setup.

    Inject this into any UI test that needs preconditions. It is the canonical
    way to create users / seed data / advance state — never click through the
    UI for setup.

    Example:
        def test_user_can_edit_profile(api_client, page):
            user = api_client.post("/api/users", json={...}).json()
            # ... auth handled via storage_state injection
            page.goto(f"/users/{user['id']}/edit")
            ...
    """
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        yield client


# --------------------------------------------------------------------------- #
# Auth — mint a session via API, inject into the browser                      #
# --------------------------------------------------------------------------- #
def _mint_session_via_api(api_client: httpx.Client, email: str, password: str) -> dict:
    """POST /auth/login → returns cookies + access_token.

    Override this in your project's conftest if your auth flow differs
    (OAuth, magic links, JWT-only, etc.).
    """
    r = api_client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"cookies": dict(r.cookies), "token": r.json().get("access_token")}


@pytest.fixture(scope="session")
def auth_storage_state(api_client: httpx.Client, base_url: str) -> dict:
    """Build a Playwright storage_state object from an API-issued session.

    This is the moral equivalent of clicking through /login — but takes 50ms
    instead of 3 seconds and never flakes on a slow form.
    """
    email = os.environ.get("TEST_USER", "test@example.com")
    password = os.environ.get("TEST_PASSWORD", "testpass")
    session = _mint_session_via_api(api_client, email, password)

    # Convert API cookies into Playwright's storage_state cookie format.
    cookies = []
    for name, value in session["cookies"].items():
        cookies.append({
            "name": name, "value": value,
            "url": base_url,  # bind to the SUT origin
            "httpOnly": True, "secure": base_url.startswith("https"),
            "sameSite": "Lax",
        })
    origins = []
    if session.get("token"):
        # Some apps store the token in localStorage rather than cookie.
        origins.append({
            "origin": base_url,
            "localStorage": [{"name": "access_token", "value": session["token"]}],
        })
    return {"cookies": cookies, "origins": origins}


@pytest.fixture()
def context(browser: Browser, base_url: str) -> Iterator[BrowserContext]:
    """Anonymous context — no auth. Use for /login, /signup, public pages."""
    ctx = browser.new_context(base_url=base_url, viewport={"width": 1920, "height": 1080})
    yield ctx
    ctx.close()


@pytest.fixture()
def authed_context(
    browser: Browser, base_url: str, auth_storage_state: dict
) -> Iterator[BrowserContext]:
    """Pre-authenticated context — session injected via API, no /login click.

    Use this for any UI test where login itself is NOT the subject of the test.
    """
    ctx = browser.new_context(
        base_url=base_url,
        viewport={"width": 1920, "height": 1080},
        storage_state=auth_storage_state,
    )
    yield ctx
    ctx.close()


@pytest.fixture()
def page(context: BrowserContext) -> Iterator[Page]:
    p = context.new_page()
    yield p
    p.close()


@pytest.fixture()
def logged_in_page(authed_context: BrowserContext) -> Iterator[Page]:
    """Authenticated page — session minted via API, NOT via /login click.

    Drop-in for the previous UI-driven login fixture. Faster, more reliable,
    and doesn't bleed login flakiness into unrelated UI tests.
    """
    p = authed_context.new_page()
    yield p
    p.close()
