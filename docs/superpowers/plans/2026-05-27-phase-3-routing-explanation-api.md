# AgentMind Phase 3 Routing Explanation API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-owned routing explanation API so the control plane can explain why a request was routed to an Agent.

**Architecture:** Introduce `RoutingExplanationService` as the aggregation boundary for route explanations. It composes `TraceService`, `AuditService`, `AgentCapabilityRegistry`, and `StrategyManager`; the panel router only adapts HTTP state and delegates to the service. This package does not add static UI and does not move explanation logic into legacy router paths.

**Tech Stack:** Python 3.12, FastAPI APIRouter, existing local SQLite-backed services, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- `RoutingExplanationService`
  - Owns explanation assembly.
  - Reads route trace through `TraceService`.
  - Reads correlated audit events through `AuditService`.
  - Reads selected agent profile through `AgentCapabilityRegistry`.
  - Reads runtime strategy status through `StrategyManager`.
- `panel/server.py`
  - Exposes `GET /panel/api/routing/explanations/{trace_id}`.
  - Builds service dependencies from `app.state`.
  - Does not assemble explanations itself.

Transition compatibility:

- Existing `/panel/api/routing/trace/{trace_id}` remains unchanged.
- Existing `/panel/api/audit/events` remains unchanged.
- If `app.state.strategy_manager` is missing in tests or older app setup, panel may create the same fallback `StrategyManager` used by `/routing/strategies`.

Not allowed:

- SQL queries in panel endpoints.
- Explanation assembly in `api/router.py` or `panel/server.py`.
- Front-end/static UI changes in this package.
- Long-term dependency on old memory trace rows beyond `TraceService` fallback.

Out of scope:

- Failed-step diagnosis for non-routing execution errors.
- UI rendering.
- ChannelHub, security policy explanation, or Phase 4 work.

## Files

Create:

- `src/agentmind/services/routing_explanation_service.py`
- `tests/test_routing_explanation_service.py`
- `docs/superpowers/plans/2026-05-27-phase-3-routing-explanation-api.md`

Modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/services/__init__.py`
- `tests/test_panel_api.py`

## Explanation Shape

For a found trace:

```python
{
    "trace_id": "t1",
    "found": True,
    "summary": "[explicit] -> a1 (conf=0.85)",
    "decision": {
        "agent_id": "a1",
        "strategy": "explicit",
        "confidence": 0.85,
        "fallback_chain": ["a2"],
        "security_flagged": False,
        "raw_message": "hello",
        "candidates": ["a1", "a2"],
    },
    "selected_agent": {"agent_id": "a1", "healthy": True},
    "strategies": [{"name": "explicit", "enabled": True}],
    "audit_events": [{"trace_id": "t1", "module": "routing"}],
}
```

For a missing trace:

```python
{
    "trace_id": "missing",
    "found": False,
    "summary": "Trace not found",
    "decision": {},
    "selected_agent": None,
    "strategies": [],
    "audit_events": [],
}
```

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_routing_explanation_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: RoutingExplanationService

**Files:**

- Create: `src/agentmind/services/routing_explanation_service.py`
- Create: `tests/test_routing_explanation_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- found trace aggregates decision, selected agent profile, strategy status, and trace-scoped audit events.
- missing trace returns a stable empty explanation.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_routing_explanation_service.py -q
```

Expected: FAIL because `RoutingExplanationService` does not exist.

- [ ] **Step 3: Implement minimal service**

Create a service with:

```python
class RoutingExplanationService:
    def __init__(self, trace_service=None, audit_service=None, capability_registry=None, strategy_manager=None):
        ...

    async def explain(self, trace_id: str) -> dict:
        ...
```

The service should parse `trace["content"]` when available, fall back to top-level trace fields, and keep missing dependencies optional.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_routing_explanation_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Explanation Endpoint

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel endpoint test**

Add `TestPanelAPI::test_routing_explanation_endpoint_uses_service` that monkeypatches `agentmind.panel.server.RoutingExplanationService`, calls:

```text
GET /panel/api/routing/explanations/t1
```

and asserts:

- Status is 200.
- Response is the service explanation.
- Service constructor receives trace/audit/capability/strategy dependencies.
- `explain()` receives `t1`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
```

Expected: FAIL with 404 because endpoint does not exist.

- [ ] **Step 3: Implement thin endpoint**

In `panel/server.py`:

- Import `RoutingExplanationService`.
- Reuse or create `StrategyManager` through the same fallback pattern as `/routing/strategies`.
- Create `AgentCapabilityRegistry(request.app.state.agent_registry)`.
- Pass dependencies into `RoutingExplanationService`.
- Return `await service.explain(trace_id)`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_routing_explanation_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_routing_explanation_endpoint_uses_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-routing-explanation-api.md src/agentmind/services/routing_explanation_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py tests/test_routing_explanation_service.py tests/test_panel_api.py
git commit -m "feat: add routing explanation api"
```
