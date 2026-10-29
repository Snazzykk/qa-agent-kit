---
name: source-aware-test-gen
description: Generate tests grounded in the SUT source code — reads artifacts/source-inventory.json (from source-code-audit) + optionally uses playwright MCP / CLI to explore the live app, then emits tests referencing REAL endpoints, Pydantic schemas, data-testids, status codes, error messages. Zero hallucination. Activate when the user says "write tests from source", "source-aware tests", "generate tests from code", "tests using real endpoints", or after source-code-audit has run.
---

# Source-Aware Test Generation

**The anti-hallucination skill.** Tests only reference artifacts that exist in the SUT source — real routes, Pydantic field names, actual `data-testid`s, specific error strings from the handler code. Powered by the inventory from `source-code-audit`, the graph built by `code-graph-analyzer`, and optional `playwright-mcp` exploration of the running app.

Instead of "load every file under `app/`" this skill **queries the code graph lazily per target** via `LazyContextLoader`, so a single test-gen run stays well under 50K tokens.

## When to Activate

- After `code-graph-analyzer` indexed the SUT and `source-code-audit` produced `artifacts/source-inventory.json` (+ `recommended_chain`).
- User says "write tests from source", "source-aware tests", "tests using real endpoints", "don't hallucinate".
- Generating regression tests for a specific PR — feed in the diff + inventory.

## LazyContextLoader — graph-backed, per-target context

```python
# tests/framework/generator/lazy_context.py
from dataclasses import dataclass
from tests.framework.codegraph import GraphQueryClient


@dataclass
class RouteContext:
    handler_source: str
    request_model_source: str | None
    response_model_source: str | None
    orm_entities_touched: list[str]
    side_effects: list[str]                   # email.send, kafka.produce, etc.


@dataclass
class FunctionContext:
    source: str
    callers: list[str]                         # one-hop
    callees: list[str]                         # one-hop


class LazyContextLoader:
    """Pulls ONLY the context needed to generate a single test,
    using the code graph. Never loads the whole repo.
    """

    def __init__(self, graph: GraphQueryClient):
        self._graph = graph

    def for_route(self, path: str) -> RouteContext:
        handler = self._graph.resolve_route_handler(path)
        return RouteContext(
            handler_source=self._graph.source_of(handler),
            request_model_source=self._graph.source_of(
                self._graph.request_model_of(handler)
            ),
            response_model_source=self._graph.source_of(
                self._graph.response_model_of(handler)
            ),
            orm_entities_touched=self._graph.orm_entities_touched_by(handler),
            side_effects=self._graph.side_effects_of(handler),
        )

    def for_function(self, symbol: str) -> FunctionContext:
        return FunctionContext(
            source=self._graph.source_of(symbol),
            callers=self._graph.query_callers(symbol, depth=1),
            callees=self._graph.query_callees(symbol, depth=1),
        )
```

The generator calls `LazyContextLoader.for_route("/api/v1/refunds")` right before writing `test_refund.py`, gets ~2-6K tokens of precisely relevant source, and nothing else.

## Routing via recommended_chain

`source-code-audit` emits `inventory.recommended_chain` (via `StackRouter`). This skill reads that list and picks per-target **templates** accordingly:

| Chain entry | Template set used |
|-------------|-------------------|
| `arch-service-object-rest` | REST handler → BaseAPI subclass + Pydantic tests |
| `arch-service-object-graphql` | GraphQL op → typed operation tests |
| `arch-service-object-grpc` | gRPC method → pb2 adapter tests |
| `arch-kafka-testing` | topic producer/consumer → `BaseKafkaTest` + `MessageAssertions` |
| `arch-message-queue-testing` | queue → `BaseQueueTest` + dead-letter / retry tests |
| `arch-websocket-testing` | WS handler → connection lifecycle + message exchange tests |
| `arch-sse-testing` | SSE endpoint → stream-assertion tests |
| `webhook-testing` | webhook receiver → signature + idempotency tests |
| `arch-clickhouse-testing` | analytics table → ingestion + query-regression tests |
| `arch-etl-pipeline-testing` | DAG → per-task + end-to-end pipeline tests |
| `arch-appium-mobile` | mobile screen → `BaseScreen` + gesture tests |
| `arch-playwright-pom` / `arch-selenium-pom` + `arch-page-components` | UI route → POM + widget tests |
| `voice-agent-testing` | voice flow → STT/TTS/barge-in tests |
| `chatbot-platform-testing` | bot handler → conversation script tests |
| `llm-agent-testing` | agent/LLM feature → semantic + tool-call tests |
| `feature-flag-testing` | flag touchpoint → variant/fallback tests |

If the recommended chain contains e.g. `arch-kafka-testing`, the generator pulls templates from that skill's `templates/` directory — never fabricates new Kafka boilerplate. A chain entry that is not installed in this project is named as missing, and the generator uses `arch-service-object-rest` / `arch-playwright-pom` instead.

## Token Budget

Thanks to `code-graph-analyzer` + `LazyContextLoader`, a full test-gen run fits comfortably in prompt budgets:

| Stage | Context pulled | ~tokens |
|-------|---------------|---------|
| Load `source-inventory.json` + `test-matrix.json` + `recommended_chain` | JSON summaries only | 2-5K |
| Per target: `LazyContextLoader.for_route(...)` | handler + 2 models + ORM touches | 3-6K |
| Per target: matching `arch-*` template (copied, not regenerated) | one template file | 1-3K |
| Optional playwright-mcp DOM snapshot for UI target | single route HTML | 2-4K |
| **Total per test-gen run (6-10 targets)** |  | **< 50K tokens** |

Contrast with the naive "read every Python file" approach which often blew past 300K tokens on medium apps. The hard rule: **never pre-load files the graph hasn't proven are needed.**

## Inputs

```
artifacts/
├── source-inventory.json   # from source-code-audit (required)
├── test-matrix.json        # from source-code-audit (required)
└── playwright-mcp/         # optional — live-DOM snapshots via MCP
    └── <route>/dom.html
```

## Generation Pipeline

```
source-inventory.json
          │
          ▼
   TargetSelector — pick P0/P1 items from test-matrix
          │
          ▼
   ┌───────────────┬──────────────┬─────────────────┐
   ▼               ▼              ▼                 ▼
REST route     GraphQL op     gRPC method      UI route
   │               │              │                 │
   ▼               ▼              ▼                 ▼
arch-service-  arch-service-  arch-service-    arch-playwright-
object-rest    object-graphql object-grpc      pom + page-object-
+ Pydantic     + operation    + pb2 adapter    generator
from models    from schema                     + playwright-mcp
   │               │              │                 │
   └───────────────┴──────────────┴─────────────────┘
                          │
                          ▼
               tests/<layer>/test_<name>.py
```

## Source-Grounding Rules

1. **Endpoints:** always the exact route from inventory (`/api/v1/users/{user_id}`), never a guess.
2. **Models:** import from `tests/services/<r>/models/`, generated from the actual Pydantic/DRF schema in SUT.
3. **Status codes:** the exact set documented in the handler's `status_code=` or raised from `HTTPException`.
4. **Error messages:** from the handler's `detail=` / `message=` constants; don't paraphrase.
5. **Selectors:** `data-testid` from the SUT JSX/TSX; if absent, emit TODO recommending the SUT team add one.
6. **Auth:** match the handler's `Depends(require_auth)` / `@login_required` — generate `BaseAuthenticatedTest` subclass.
7. **Side effects:** if handler calls `email.send(...)`, the test must assert the email mock was called.

## OOP Target Shape

```python
# tests/api/test_refund.py   (generated source-aware)
import pytest
import allure

from tests.framework.base_test import BaseAuthenticatedTest
from tests.framework.assertions import Assertions
from tests.services.billing.api import BillingAPI
from tests.services.billing.models.refund import RefundResponse, RefundRequest
from tests.services.billing.factories.refund_factory import RefundRequestFactory


@allure.feature("Billing / Refund")
@pytest.mark.critical
class TestRefundPartial(BaseAuthenticatedTest):
    """SOURCE: app/api/billing/refund.py:refund_handler.

    DetectedStack: fastapi + sqlalchemy + pydantic + aiokafka
    Generated via: arch-service-object-rest   (recommended_chain[0])
    Graph-queried context: handler + RefundRequest + RefundResponse + Order ORM.

    Handler imports asserted:
      - status 200 on success, 422 on amount>order_total, 404 on missing order
      - error detail "amount exceeds order total" (line 61)
      - emits `refund.created` event (line 78) — assert via event mock
    """

    @pytest.fixture(autouse=True)
    def _setup(self, authenticated_client, event_mock):
        self.billing = BillingAPI(authenticated_client)
        self.events = event_mock  # provided by source-aware conftest

    @pytest.mark.smoke
    @allure.story("Happy path: partial refund of $5 on $10 order")
    def test_partial_refund_succeeds(self, order_with_total_10):
        request = RefundRequestFactory.for_order(order_with_total_10, amount=5.00)
        response = self.billing.create_refund(request)
        refund = Assertions.assert_schema(response, RefundResponse)
        assert refund.status == "succeeded"
        assert refund.amount == 5.00
        self.events.assert_emitted("refund.created", payload={"order_id": order_with_total_10.id})

    @allure.story("Refund amount exceeds order total → 422")
    def test_refund_exceeding_total_returns_422(self, order_with_total_10):
        request = RefundRequestFactory.for_order(order_with_total_10, amount=15.00)
        response = self.billing.create_refund(request, success=False)
        Assertions.assert_error(response, 422, "amount exceeds order total")
```

## UI economy rule (mandatory for every UI test)

When emitting a `[ui]` test, the generator MUST split the case into:

1. **`setup_state` — API-only preconditions** (resolved from `source-inventory.json`).
   For every entity referenced in the case (e.g. "delete an existing ad"), look up the
   matching POST/PUT route in the inventory and call it via `self.api`.
2. **`test_*` — only the UI flow under verification** (clicks/keyboard/assertions on rendered DOM).
3. **`teardown_state` — API-only cleanup** (DELETE / soft-delete via the inventory).

If the case wording is "create X then delete X" but the only thing under test is the delete UI,
emit ONE test where create is in `setup_state` and only delete is in the test body. Do NOT
chain two UI flows.

```python
# ❌ Generator must NOT emit this — clicks through create just to test delete
def test_user_can_delete_ad(self):
    self.checkout.open().fill_card_number(...).click_pay()  # create flow — wrong
    self.ads_list.click_delete()                             # the actual subject

# ✅ Generator emits this — precondition via API, UI for the action under test
class TestDeleteAd(BaseE2ETest):
    def setup_state(self):
        # Resolved from inventory: POST /api/ads
        self.ad = self.api.post("/api/ads", json={"title": "iPhone 15", ...}).json()
    def test_owner_can_delete_their_ad(self):
        self.page.goto(f"/ads/{self.ad['id']}")
        AdPage(self.page).click_delete().confirm()
        AdPage(self.page).expect_toast("Deleted")
    def teardown_state(self):
        self.api.delete(f"/api/ads/{self.ad['id']}")  # 404 is fine if delete succeeded
```

Validation: after generation, the `[ui] surface` block in `artifacts/generation-log.md`
lists each emitted test alongside the API routes it used for setup/cleanup. If any UI test
appears with no `setup:` API calls *and* mutates state, the run flags it as `WARN — possible
double-click; subject of test unclear`.

## UI Test Grounded in JSX testids

```python
# tests/e2e/test_checkout.py   (generated source-aware)
import pytest
import allure

from tests.framework.base_test import BaseE2ETest
from tests.e2e.pages.checkout_page import CheckoutPage


@allure.feature("Checkout")
@pytest.mark.critical
class TestCheckoutWithCard(BaseE2ETest):
    """SOURCE: web/app/checkout/page.tsx + web/components/PaymentForm.tsx.

    DetectedStack: next.js + react (UI) + fastapi + stripe (backend)
    Generated via: arch-playwright-pom + arch-page-components   (recommended_chain[1..2])
    Graph-queried context: page.tsx testids + PaymentForm component tree.

    data-testids used (all present in SUT):
      - card-number-input, cvv-input, expiry-input
      - pay-now-button
      - confirmation-heading (rendered after redirect to /order/{id})
    Backend contract: POST /api/v1/checkout returns 201 + {order_id}.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.checkout = CheckoutPage(self.page, self.base_url)

    @pytest.mark.smoke
    def test_pay_with_valid_card_completes_order(self):
        self.checkout.open() \
            .fill_card_number("4242 4242 4242 4242") \
            .fill_cvv("123") \
            .fill_expiry("12/30") \
            .click_pay() \
            .assert_order_confirmed()
```

## Playwright-MCP Integration (optional)

When `playwright-mcp` is available, the skill:

1. Navigates to each UI route from inventory.
2. Captures DOM + network traffic.
3. Cross-references real DOM with SUT source to pick the strongest selector that *exists* on the page.
4. Confirms API call shape matches Pydantic model.

If a mismatch is found (e.g. inventory says status 200 but live returns 302 redirect), emit a **warning** in the test file rather than generating a wrong test.

## Output

Per target, emits:

- `tests/<layer>/test_<resource>.py` — the source-aware test.
- `tests/<layer>/README.md` updated with "Source refs" table linking tests to SUT files.
- `artifacts/generation-log.md` — for each generated test: resolved route, model, selectors, and any TODOs (e.g. "add data-testid to Pay button").

## Example Session

**User says:** "Using the inventory, write tests for all P0 items."

**Skill does:**
1. Loads inventory + matrix.
2. Picks 6 P0 critical tests.
3. For each:
   - If API → calls `arch-service-object-rest`/`graphql`/`grpc` + generates tests.
   - If UI → calls `arch-playwright-pom` (if framework missing) + `page-object-generator` + writes test.
4. For every generated file, logs source refs in `artifacts/generation-log.md`.
5. Runs `pytest --collect-only` — reports collect errors as TODOs.

## Common Pitfalls

- Never assume a status code — read it from the handler.
- Never assume a field name — import the Pydantic model and use it.
- Never invent an error message — copy from `detail=` in code.
- When `data-testid` is missing in SUT JSX, emit a TODO asking the SUT team to add it; don't fall back to brittle CSS/XPath.
- If SUT reveals rate-limiting / idempotency keys, the test must respect them.

## Related Skills

- `code-graph-analyzer` — mandatory prerequisite; provides `GraphQueryClient` / `StackDetector` / `DetectedStack` that power `LazyContextLoader`.
- `source-code-audit` — mandatory prerequisite (builds the inventory + `recommended_chain` via `StackRouter`).
- `arch-service-object-rest` / `arch-service-object-graphql` / `arch-service-object-grpc` — REST/GraphQL/gRPC code targets.
- `arch-kafka-testing`, `arch-message-queue-testing`, `arch-websocket-testing`, `arch-sse-testing`, `webhook-testing` — event/streaming targets.
- `arch-clickhouse-testing`, `arch-etl-pipeline-testing` — data targets.
- `arch-playwright-pom` / `arch-selenium-pom` / `arch-page-components` / `page-object-generator` / `arch-appium-mobile` — UI & mobile layer.
- `voice-agent-testing`, `chatbot-platform-testing`, `llm-agent-testing`, `feature-flag-testing` — platform targets.
- `contract-testing` — upgrade path from example-based to contract tests.
- `production-error-to-regression-test` — inverse: prod error → SUT-grounded regression.
