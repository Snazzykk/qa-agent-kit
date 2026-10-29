---
name: page-object-generator
description: Generate a Playwright Page Object class (OOP, inherits BasePage) from a URL or HTML snapshot — locator @property getters, semantic action methods with @allure.step, fluent return-self interface, stable-selector strategy. Activate when the user says "page object", "POM", "generate playwright class".
---

# Page Object Generator — OOP

Generates a concrete `Page` subclass of `BasePage` from a live URL or HTML snapshot. Every generated class follows the **one-page-one-class, property-locators, fluent-actions** pattern.

## Output Conventions

- Inherits `BasePage` from `playwright-bootstrap`.
- `url_path` attribute defines the page path.
- Locators exposed as `@property` (never stored as eager `page.locator(...)` attributes).
- Action methods decorated with `@allure.step`.
- Fluent methods return `self` for chaining.
- Assertions live on the page class, not in tests.

## Selector Priority

1. `page.get_by_test_id(...)` if `data-testid` / `data-test` / `data-cy` exists
2. `page.get_by_role(role, name=...)` for buttons/links/headings
3. `page.get_by_label(text)` for form controls
4. `page.get_by_text(text, exact=True)` for unique text
5. CSS selector as last resort (leave TODO comment)

## Generated Class Shape

```python
# tests/e2e/pages/checkout_page.py
import allure
from playwright.sync_api import expect

from tests.e2e.pages.base_page import BasePage


class CheckoutPage(BasePage):
    url_path = "/checkout"

    # --- Locators (lazy via @property) ---
    @property
    def card_number_input(self):
        return self.page.get_by_test_id("card-number")

    @property
    def cvv_input(self):
        return self.page.get_by_test_id("cvv")

    @property
    def pay_button(self):
        return self.page.get_by_role("button", name="Pay")

    @property
    def confirmation_heading(self):
        return self.page.get_by_role("heading", name="Thank you")

    # --- Actions (fluent, Allure-annotated) ---
    @allure.step("Fill card number")
    def fill_card_number(self, number: str) -> "CheckoutPage":
        self.card_number_input.fill(number)
        return self

    @allure.step("Fill CVV")
    def fill_cvv(self, cvv: str) -> "CheckoutPage":
        self.cvv_input.fill(cvv)
        return self

    @allure.step("Click Pay")
    def click_pay(self) -> None:
        self.pay_button.click()

    @allure.step("Complete payment: card={card_number}")
    def pay_with(self, *, card_number: str, cvv: str) -> None:
        self.fill_card_number(card_number).fill_cvv(cvv).click_pay()

    # --- Assertions (live on the page, not in tests) ---
    @allure.step("Assert confirmation visible")
    def assert_payment_succeeded(self) -> None:
        expect(self.confirmation_heading).to_be_visible()
```

## Component Extraction

When a page has a repeating widget (row, modal, card), emit a `BaseComponent` subclass:

```python
# tests/e2e/pages/components/order_row.py
from playwright.sync_api import Locator

from tests.e2e.pages.base_page import BaseComponent


class OrderRow(BaseComponent):
    """Represents a single order row in OrdersPage."""

    @property
    def title(self):
        return self.root.get_by_test_id("order-title")

    @property
    def edit_button(self):
        return self.root.get_by_role("button", name="Edit")

    def click_edit(self) -> None:
        self.edit_button.click()
```

Parent page exposes a factory:

```python
class OrdersPage(BasePage):
    url_path = "/orders"

    def order_by_id(self, order_id: str) -> OrderRow:
        root = self.page.get_by_test_id(f"order-{order_id}")
        return OrderRow(root)
```

## Usage in Tests

```python
@allure.feature("Checkout")
class TestCheckout(BaseE2ETest):
    @pytest.fixture(autouse=True)
    def _setup_pages(self):
        self.checkout = CheckoutPage(self.page, self.base_url)

    @pytest.mark.smoke
    def test_pay_with_valid_card(self):
        self.checkout.open()
        self.checkout.pay_with(card_number="4242 4242 4242 4242", cvv="123")
        self.checkout.assert_payment_succeeded()
```

## iframe / Shadow DOM

Generate using `frame_locator` — exposed as a property on the page class:

```python
class StripeCheckoutPage(BasePage):
    url_path = "/checkout"

    @property
    def stripe_frame(self):
        return self.page.frame_locator("iframe[name='__stripe']")

    @property
    def card_number_input(self):
        return self.stripe_frame.get_by_placeholder("Card number")
```

## Common Pitfalls

- Don't store `self.email_input = page.get_by_label("Email")` as an instance attr in `__init__` — if the page reloads, the handle is stale. Use `@property`.
- Don't expose `self.page.locator(...)` in tests — tests touch only page methods.
- Don't name methods after selectors (`click_button_a`) — name after intent (`submit_form`).
- If multiple elements match role+name, anchor via a parent component; don't use `.first`.

## Related Skills

- `playwright-bootstrap` — prerequisite, defines `BasePage`, `BaseComponent`.
- `playwright-codegen-enhancer` — alternative input (recorded code → OOP refactor).
- `selector-healer` — heal selectors after UI changes.
- `visual-regression`, `accessibility-a11y` — extend the generated pages.
