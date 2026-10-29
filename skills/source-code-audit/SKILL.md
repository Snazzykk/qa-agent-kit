---
name: source-code-audit
description: Read the System-Under-Test source code (FastAPI / Django / Flask / Express / Next.js / gRPC / GraphQL) and produce a risk-weighted test plan — detected routes, auth boundaries, state-mutating operations, data models, UI pages, external integrations, edge cases. Outputs test-plan.md + an inventory JSON that other skills consume. Activate when the user says "audit the product", "product review", "scan source code for tests", "what should we test", "test plan from code".
---

# Source Code Audit — SUT → Test Plan

**This is the flagship source-aware skill.** Reads the actual product source code and emits:

1. `artifacts/source-inventory.json` — machine-readable map of routes, models, pages, events, externals.
2. `docs/test-plan.md` — risk-weighted what-to-automate plan for humans.
3. `artifacts/test-matrix.json` — machine-readable matrix consumed by `source-aware-test-gen` and `playwright-mcp` generators.
4. `artifacts/recommended-chain.json` — ordered list of `arch-*` / generator skills to invoke next, emitted by the new `StackRouter`.

Downstream skills use this output so tests never hallucinate endpoints, payloads, selectors, or status codes — they reference **real** source-code artifacts.

## Code-Graph Integration (NEW)

This skill assumes `code-graph-analyzer` has indexed the SUT first (see the Flagship chain in `CLAUDE.md`). When the graph is available, the pipeline swaps direct filesystem scanning for typed graph queries:

```python
# tests/framework/codegraph/ — produced by code-graph-analyzer
from pathlib import Path
from tests.framework.codegraph import GraphQueryClient, StackDetector, DetectedStack

graph = GraphQueryClient(provider)                # the provider code-graph-analyzer set up
stack: DetectedStack = StackDetector(Path(".")).detect()

routes   = graph.find_routes()                    # all HTTP routes w/ handler symbols
handlers = graph.find_callers("refund_handler")
models   = graph.find_models()
shape    = graph.shape_of("POST /refunds")        # request/response shape of one endpoint
```

If the graph isn't indexed (or a pattern isn't modeled), the existing pathlib/AST scanner still runs as a **fallback** — this change is additive. Every scanner class in the OOP pipeline now accepts an optional `graph: GraphQueryClient | None` and prefers it when present.

## When to Activate

- Onboarding: joined a project, need to know what to test.
- Pre-release: what's risky to ship?
- Before `source-aware-test-gen` or `api-test-generator` / `page-object-generator` (enriches their output).
- User says "audit the product", "review source", "product review", "scan source for tests".

## SourceInventory Dataclass

```python
# tests/framework/audit/inventory.py
from dataclasses import dataclass, field
from tests.framework.codegraph import DetectedStack


@dataclass
class SourceInventory:
    stack: dict                                   # legacy freeform stack summary
    routes: list[dict] = field(default_factory=list)
    graphql: dict = field(default_factory=dict)
    grpc: dict = field(default_factory=dict)
    models: list[dict] = field(default_factory=list)
    ui_pages: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    externals: list[dict] = field(default_factory=list)
    # --- NEW fields (populated when code-graph + StackRouter run) ---
    detected_stack: DetectedStack | None = None
    recommended_chain: tuple[str, ...] = ()
```

## Inventory Schema

```jsonc
// artifacts/source-inventory.json
//
// schema_version must be present: the skills that read the inventory check it
// first. Bump it when the schema breaks compatibility.
{
  "schema_version": 1,
  "generated_at": "2026-04-29T18:00:00Z",
  "generator": "source-code-audit (Agent Mode for Python QA v3.1+)",
  "stack": {
    "backend": "fastapi|django|flask|express|nestjs|go|rails",
    "frontend": "next.js|react|vue|angular|none",
    "protocols": ["rest", "graphql", "grpc", "websocket"],
    "db": ["postgres", "redis", "clickhouse"]
  },
  "detected_stack": {
    // serialized DetectedStack from code-graph-analyzer.StackDetector
    "web_frameworks": ["fastapi"],
    "orm": ["sqlalchemy"],
    "validation": ["pydantic"],
    "messaging": ["aiokafka"],
    "streaming": [],
    "data": ["clickhouse-connect"],
    "platforms": [],
    "llm": [],
    "ui": {"frontend": "next.js", "browser_tests": null, "mobile": null},
    "feature_flags": []
  },
  "recommended_chain": [
    "arch-service-object-rest",
    "arch-kafka-testing",
    "arch-clickhouse-testing",
    "source-aware-test-gen"
  ],
  "routes": [
    {
      "method": "POST",
      "path": "/api/v1/users",
      "handler": "app/api/users.py:create_user",
      "auth": "bearer|api_key|public|cookie",
      "request_model": "CreateUserRequest",
      "response_model": "UserResponse",
      "status_codes": [201, 400, 409, 422],
      "mutates": ["User", "AuditLog"],
      "side_effects": ["email.send", "analytics.track"],
      "risk": "high",
      "reasons": ["writes", "PII", "auth-protected"]
    }
  ],
  "graphql": {
    "queries": [{"name": "viewer", "response_type": "User", "auth": "bearer"}],
    "mutations": [{"name": "createUser", "input_type": "CreateUserInput"}]
  },
  "grpc": {
    "services": [{"name": "UserService", "methods": [{"name": "GetUser", "streaming": "unary"}]}]
  },
  "models": [
    {
      "name": "User",
      "file": "app/models/user.py",
      "fields": [{"name": "email", "type": "str", "constraints": ["unique", "email"]}],
      "relations": [{"name": "posts", "to": "Post", "cardinality": "1:N"}]
    }
  ],
  "ui_pages": [
    {
      "route": "/login",
      "file": "app/pages/login.tsx",
      "components": ["LoginForm"],
      "testids": ["email-input", "password-input", "submit-button"],
      "actions": ["fill email", "fill password", "click submit"],
      "flows": ["valid login", "invalid credentials", "password reset"]
    }
  ],
  "events": [
    {"name": "user.created", "producer": "create_user", "consumers": ["email-service"]}
  ],
  "externals": [
    {"name": "Stripe", "auth": "api_key", "endpoints_used": ["/v1/charges", "/v1/customers"]}
  ]
}
```

## Detection Strategy (per stack)

| Stack | Signals Claude scans |
|-------|----------------------|
| FastAPI | `@app.get/post/put/patch/delete`, `APIRouter`, `Depends(...)`, `response_model=`, Pydantic models under `app/schemas` |
| Django | `urlpatterns`, `@api_view`, DRF `ViewSet`, `serializers.py`, `models.py` |
| Flask | `@app.route`, `Blueprint`, `request.get_json()`, schema decorators |
| Express / NestJS | `app.use(router)`, `@Controller`, `@Get/@Post`, zod/joi schemas |
| GraphQL | `schema.graphql` / `typeDefs`, resolvers, directive `@auth` |
| gRPC | `.proto` files → service+method extraction |
| Next.js UI | `pages/` or `app/`, React components with `data-testid`, form handlers |
| DB | migrations (alembic/django/knex) for tables + constraints |

## StackRouter — DetectedStack → RecommendedChain

```python
# tests/framework/audit/stack_router.py
from dataclasses import dataclass
from tests.framework.codegraph import DetectedStack


@dataclass(frozen=True)
class RecommendedChain:
    skills: list[str]                     # ordered skill names to invoke

    def as_tuple(self) -> tuple[str, ...]:
        return tuple(self.skills)


class StackRouter:
    """Maps a DetectedStack (from code-graph-analyzer.StackDetector)
    to an ordered list of skill names to invoke next.

    The router is additive: if multiple categories match, chains are
    concatenated in priority order (API > events > data > UI > platform)
    and source-aware-test-gen is always the tail.
    """

    def route(self, stack: DetectedStack) -> RecommendedChain:
        chain: list[str] = []

        # ---- API layer ----
        if "fastapi" in stack.web_frameworks or "flask" in stack.web_frameworks:
            chain += ["arch-service-object-rest", "api-test-generator"]
        if "django" in stack.web_frameworks:            # DRF implied
            chain += ["arch-service-object-rest", "api-test-generator"]
        if stack.has_any("graphene", "strawberry", "sgqlc", "ariadne"):
            chain += ["arch-service-object-graphql"]
        if "grpcio" in stack.rpc:
            chain += ["arch-service-object-grpc"]

        # ---- Event / streaming ----
        if stack.has_any("kafka-python", "aiokafka", "confluent-kafka"):
            chain += ["arch-kafka-testing"]
        if stack.has_any("pika", "aio-pika") or stack.has_queue("sqs"):
            chain += ["arch-message-queue-testing"]
        if stack.has_any("websockets") or stack.has_fastapi_websocket():
            chain += ["arch-websocket-testing"]
        if "sse-starlette" in stack.streaming:
            chain += ["arch-sse-testing"]
        if stack.has_webhook_receivers():
            chain += ["webhook-testing"]

        # ---- Data ----
        if stack.has_any("clickhouse-driver", "clickhouse-connect"):
            chain += ["arch-clickhouse-testing"]
        if stack.has_any("airflow", "prefect", "dagster", "dbt"):
            chain += ["arch-etl-pipeline-testing"]

        # ---- UI ----
        if stack.ui.browser_tests == "playwright":
            chain += ["arch-playwright-pom", "arch-page-components"]
        elif stack.ui.browser_tests == "selenium":
            chain += ["arch-selenium-pom", "arch-page-components"]
        if stack.ui.mobile == "appium":
            chain += ["arch-appium-mobile"]

        # ---- AI / agent / voice / chatbot ----
        if stack.has_any("twilio", "vapi", "retell", "livekit"):
            chain += ["voice-agent-testing"]
        if stack.has_any("rasa", "botpress", "dialogflow") or stack.has_bedrock_agents():
            chain += ["chatbot-platform-testing"]
        if stack.has_any("langchain", "llamaindex", "openai-agents", "anthropic"):
            chain += ["llm-agent-testing"]

        # ---- Feature flags ----
        if stack.has_any("launchdarkly", "unleash", "split", "growthbook", "flagsmith"):
            chain += ["feature-flag-testing"]

        # De-dupe while preserving order, always append source-aware-test-gen
        seen, ordered = set(), []
        for skill in chain:
            if skill not in seen:
                seen.add(skill)
                ordered.append(skill)
        if "source-aware-test-gen" not in seen:
            ordered.append("source-aware-test-gen")
        return RecommendedChain(skills=ordered)
```

The router result is serialized into both `artifacts/recommended-chain.json` and the `recommended_chain` field of `SourceInventory`.

## Stack Detection Matrix

| Detected signal | Recommended chain (arch-* → source-aware-test-gen) |
|-----------------|---------------------------------------------------|
| `fastapi` + `sqlalchemy` + `pydantic` | `arch-service-object-rest` → `api-test-generator` → `source-aware-test-gen` |
| `django` + `djangorestframework` | `arch-service-object-rest` → `api-test-generator` → `source-aware-test-gen` |
| `flask` + `pydantic`/`marshmallow` | `arch-service-object-rest` → `api-test-generator` → `source-aware-test-gen` |
| `graphene` / `strawberry` / `sgqlc` / `ariadne` | `arch-service-object-graphql` → `source-aware-test-gen` |
| `grpcio` (proto files present) | `arch-service-object-grpc` → `source-aware-test-gen` |
| `kafka-python` / `aiokafka` / `confluent-kafka` | `arch-kafka-testing` → `source-aware-test-gen` |
| `pika` / `aio-pika` / `boto3` + SQS | `arch-message-queue-testing` → `source-aware-test-gen` |
| `clickhouse-driver` / `clickhouse-connect` | `arch-clickhouse-testing` → `source-aware-test-gen` |
| `airflow` / `prefect` / `dagster` / `dbt` | `arch-etl-pipeline-testing` → `source-aware-test-gen` |
| `websockets` / `fastapi.WebSocket` | `arch-websocket-testing` → `source-aware-test-gen` |
| `sse-starlette` | `arch-sse-testing` → `source-aware-test-gen` |
| Webhook receivers (e.g. `/webhooks/*` POST + HMAC verify) | `webhook-testing` |
| `playwright` in `tests/` | `arch-playwright-pom` → `arch-page-components` → `source-aware-test-gen` |
| `selenium` in `tests/` | `arch-selenium-pom` → `arch-page-components` → `source-aware-test-gen` |
| `appium-python-client` | `arch-appium-mobile` → `source-aware-test-gen` |
| `twilio` / `vapi` / `retell` / `livekit` | `voice-agent-testing` |
| `rasa` / `botpress` / `dialogflow` / Bedrock agents | `chatbot-platform-testing` |
| `langchain` / `llamaindex` / OpenAI agents / `anthropic` | `llm-agent-testing` |
| `launchdarkly` / `unleash` / `split` / `growthbook` / `flagsmith` | `feature-flag-testing` |

## Risk Scoring

Per route/page, score on:

- **Impact:** writes + auth + PII + money → high
- **Likelihood of regression:** churn (git log 90d), cyclomatic complexity
- **External dependencies:** third-party API calls → +1
- **State machine complexity:** explicit state enum, FSM → +1

Final risk = weighted sum, buckets: `critical` / `high` / `medium` / `low` / `trivial`.

## test-plan.md Layout

```markdown
# Test Plan — <Product Name>

## Stack Summary
- Backend: FastAPI 0.111, Postgres, Redis
- Frontend: Next.js 14, TanStack Query
- Integrations: Stripe (payment), SendGrid (email), Segment (analytics)

## Risk-Ranked Areas

### 🔴 Critical — automate first (top 10)
| Priority | Area | File | Type | Reasons |
|---------|------|------|------|---------|
| P0 | POST /api/v1/refunds | billing/refund.py | API + E2E | writes, money, external Stripe |
| P0 | /checkout page | pages/checkout.tsx | E2E + visual | revenue path |
| P1 | POST /auth/reset-password | auth/reset.py | API + security | auth boundary, email side-effect |
...

## Recommended Test Stack

- API tests: `arch-service-object-rest` (REST) + `arch-service-object-graphql` (GraphQL)
- UI tests: `arch-playwright-pom`
- Components library: `arch-page-components`
- Specialized: `llm-agent-testing` (chat feature), `visual-regression` (/checkout), `accessibility-a11y` (public pages)
- Contract: `contract-testing` between billing ↔ user-service

## Coverage Matrix

| Layer | Count | Priority 0 | Priority 1 | Priority 2 |
|-------|-------|-----------|-----------|-----------|
| REST endpoints | 48 | 6 | 14 | 28 |
| GraphQL mutations | 12 | 3 | 5 | 4 |
| UI critical paths | 8 | 3 | 3 | 2 |

## Phase Plan

### Phase 1 (2 weeks, ~20h)
- Scaffold framework: `arch-service-object-rest` + `arch-playwright-pom`
- Cover all P0 API + P0 E2E flows
- Acceptance: P0 suite green on staging

### Phase 2 (2 weeks, ~16h) ...

## Risks / Gotchas Found in Source

- `refund.py:48` uses raw SQL with string interpolation — inject risk (add SQL injection test)
- `/api/v1/users` has no rate limiting — add abuse test
- Auth middleware skipped on `/internal/*` — verify network boundary
- `create_user` sends welcome email *before* DB commit — race condition risk
```

## Output to Other Skills

```python
# Pseudocode — how other skills consume this inventory
inventory = json.loads(Path("artifacts/source-inventory.json").read_text())

# api-test-generator pulls real routes
for route in inventory["routes"]:
    if route["risk"] in ("critical", "high"):
        generate_test(route)

# page-object-generator reads real testids
for page in inventory["ui_pages"]:
    generate_pom(page["route"], page["testids"])

# test-data-factory reads model constraints
for model in inventory["models"]:
    generate_factory(model)
```

## Example Session

**User says:** "Audit /Users/me/Code/my-saas — make me a test plan."

**Skill does:**
1. Detects: FastAPI backend, Next.js frontend, Postgres, Stripe.
2. Scans: 48 REST routes, 8 UI pages, 23 Pydantic models.
3. Computes risk: 6 critical, 14 high, 28 medium/low.
4. Emits:
   - `artifacts/source-inventory.json` (full map, with `schema_version: 1` field)
   - `artifacts/test-matrix.json` (per-test-case matrix)
   - `docs/test-plan.md` (human-readable)
5. Suggests skill chain: `arch-service-object-rest` → `arch-playwright-pom` → `source-aware-test-gen` for the top-10 P0s.

## Common Pitfalls

- Don't generate tests yet — that's `source-aware-test-gen`'s job.
- Handle monorepos: accept `services/*` glob.
- Don't embed secrets from `.env` into inventory.
- Prefer `data-testid` attributes as they exist in source; where absent, recommend adding them before generating E2E.
- Frontend component trees can be huge — cap depth at 3 levels from routes.

## Related Skills

- `code-graph-analyzer` — prerequisite; indexes the SUT so this skill can replace filesystem scanning with typed graph queries.
- `source-aware-test-gen` — consumes inventory + `recommended_chain` to write tests that reference real source.
- `arch-playwright-pom`, `arch-selenium-pom`, `arch-service-object-rest`, `arch-service-object-graphql`, `arch-service-object-grpc` — chosen via `StackRouter` based on detected stack.
- `arch-kafka-testing`, `arch-message-queue-testing`, `arch-websocket-testing`, `arch-sse-testing`, `webhook-testing` — Second Wave event/streaming targets.
- `arch-clickhouse-testing`, `arch-etl-pipeline-testing` — Second Wave data targets.
- `arch-appium-mobile`, `voice-agent-testing`, `chatbot-platform-testing`, `feature-flag-testing`, `llm-agent-testing` — Second Wave platform targets.
- `test-plan-generator` — complementary: generate plan from a PRD instead.
- `coverage-gap-finder` — pairs with this to show where existing coverage is thin.
