"""BaseE2ETest — enforces the UI-economy rule by class shape.

USAGE
-----
    class TestEditUserProfile(BaseE2ETest):
        '''Tests ONLY the edit-profile UI. Setup happens via API.'''

        def setup_state(self) -> None:
            # 1️⃣ Create the user via API — fast, no clicks.
            self.user = self.api.post(
                "/api/users",
                json={"email": "u@x.test", "password": "p", "name": "U"},
            ).json()

        @allure.title("User can edit their profile email")
        def test_edit_email(self) -> None:
            # 2️⃣ Auth is already injected via storage_state (no /login click).
            # 3️⃣ Navigate to the page under test.
            self.page.goto(f"/users/{self.user['id']}/edit")

            # 4️⃣ The ONE UI interaction this test exists to verify.
            edit = EditProfilePage(self.page)
            edit.fill_email("new@x.test").click_save()

            # 5️⃣ Assert UI outcome (the API outcome is verified by api-tests).
            edit.expect_toast("Profile updated")

        def teardown_state(self) -> None:
            # 6️⃣ Cleanup via API — fast, no UI navigation.
            self.api.delete(f"/api/users/{self.user['id']}")

THE RULE
--------
- `setup_state` — API only. Create users, seed records, advance state.
- `test_*`      — drive only the UI surface that this test exists to verify.
- `teardown_state` — API only. Delete what you created.

Anything else is a smell:
  - Clicking through /signup just to get a user → wasted seconds, double surface.
  - Asserting on backend state via API in the same test → split it into two tests.
  - Long sequence of UI clicks before the actual assertion → re-architect: pin
    the prerequisite state via API, click only the verified flow.

Target pyramid (audited by `project-audit`):
    [unit]        ~60-70%
    [integration] ~20-30%
    [e2e]+[ui]    ~10-15%   ← UI tests are the most expensive; spend them well.
"""
from __future__ import annotations

from typing import Any

import allure
import httpx
import pytest
from playwright.sync_api import Page


@pytest.mark.usefixtures("logged_in_page", "api_client")
class BaseE2ETest:
    """Base class for UI tests that need API-driven preconditions.

    Subclasses MUST:
      - implement `setup_state()` for API-only preconditions
      - implement `teardown_state()` for API-only cleanup
      - drive only one focused UI flow per `test_*` method
    """

    page: Page
    api: httpx.Client

    @pytest.fixture(autouse=True)
    def _bind_fixtures(
        self, logged_in_page: Page, api_client: httpx.Client
    ) -> None:
        self.page = logged_in_page
        self.api = api_client
        self.setup_state()
        yield
        try:
            self.teardown_state()
        except Exception as exc:  # noqa: BLE001
            allure.attach(
                str(exc),
                name="teardown_state failure",
                attachment_type=allure.attachment_type.TEXT,
            )

    # ---- subclass hooks ---------------------------------------------------- #
    def setup_state(self) -> None:
        """Override — perform API-only preconditions here. NEVER click."""

    def teardown_state(self) -> None:
        """Override — perform API-only cleanup here. NEVER click."""

    # ---- guards ----------------------------------------------------------- #
    def fail_if_clicking_for_setup(self, reason: str) -> None:
        """Call this if you catch yourself reaching for the page in setup.

        Forces the test to stop and re-think. Use the API client instead.
        """
        pytest.fail(
            f"UI-economy rule violated in {self.__class__.__name__}: {reason}\n"
            "→ Move this state setup to setup_state() via self.api.* — "
            "UI tests verify UI behavior, they don't click through unrelated "
            "flows to get into position."
        )
