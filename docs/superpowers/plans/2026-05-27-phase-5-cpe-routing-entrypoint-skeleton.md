# Phase 5 CPE Routing Entrypoint Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-level routing CPE request builder so later packages have a clear place to call CPE, without changing routing behavior.

**Architecture:** `agentmind.governance` owns CPE request/decision contracts. `RoutingService` is the future service-layer caller for route-request governance, while panel/API/channel handlers remain adapters. This package adds a pure helper seam only; it does not call CPE from the live route path and does not replace `SensitiveScanner` or `CandidatePool`.

**Tech Stack:** Python dataclasses, pytest unit/architecture tests, existing `RoutingService`, existing `CPERequest`.

---

## Scope

Modify:

- `src/agentmind/services/routing_service.py`
- `tests/test_governance_skeleton.py`
- `docs/phase5/phase-5-readiness.md`

Create:

- `tests/test_cpe_routing_entrypoint.py`
- `docs/superpowers/plans/2026-05-27-phase-5-cpe-routing-entrypoint-skeleton.md`

Do not modify `RoutingPipeline`, `SensitiveScanner`, `CandidatePool`, memory retrieval, panel, channels, or executors.

## Non-Goals

- Do not call CPE from `_route_request_impl`.
- Do not call CPE from `route_stream`.
- Do not replace `_step_security_intercept`.
- Do not replace `SensitiveScanner` or `CandidatePool`.
- Do not block, reroute, or require approval based on CPE.
- Do not record CPE audit events from routing yet.
- Do not touch private memory retrieval behavior.

## Task 1: RED Routing CPE Entrypoint Tests

**Files:**
- Create: `tests/test_cpe_routing_entrypoint.py`
- Modify: `tests/test_governance_skeleton.py`

- [ ] **Step 1: Add failing helper test**

Create `tests/test_cpe_routing_entrypoint.py`:

```python
from types import SimpleNamespace


def test_routing_service_builds_cpe_request_for_routing_context():
    from agentmind.governance import CPERequest
    from agentmind.services.routing_service import _build_cpe_request_for_routing

    registry = SimpleNamespace(
        executors={
            "local_agent": SimpleNamespace(
                capability=SimpleNamespace(security_level="local")
            ),
            "cloud_agent": SimpleNamespace(
                capability=SimpleNamespace(security_level="cloud")
            ),
        }
    )

    request = _build_cpe_request_for_routing(
        trace_id="t-route",
        user_id="u1",
        agent_id="cloud_agent",
        message="hello",
        agent_registry=registry,
        memories=[{"memory_id": "m1", "access_level": "public"}],
    )

    assert isinstance(request, CPERequest)
    assert request.trace_id == "t-route"
    assert request.user_id == "u1"
    assert request.agent_id == "cloud_agent"
    assert request.agent_security_level == "cloud"
    assert request.context == {"message": "hello", "surface": "routing"}
    assert request.memory_items == [{"memory_id": "m1", "access_level": "public"}]
```

- [ ] **Step 2: Update architecture test to allow only RoutingService seam**

Modify `tests/test_governance_skeleton.py` so `ROUTER_SERVICE` is not in the blanket "no governance import" list, then add a test that asserts `RoutingService` imports governance only for `_build_cpe_request_for_routing` and does not call `CPE().evaluate`.

Use this code:

```python
def test_governance_skeleton_is_not_wired_into_runtime_adapters_or_memory_yet():
    checked_paths = [
        PANEL_SERVER,
        MEMORY_SERVICE,
        *CHANNELS_DIR.glob("*.py"),
    ]
    offenders = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        if "agentmind.governance" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_routing_service_only_has_cpe_request_builder_seam():
    text = ROUTER_SERVICE.read_text(encoding="utf-8")

    assert "agentmind.governance" in text
    assert "def _build_cpe_request_for_routing" in text
    assert "CPE().evaluate" not in text
    assert "record_cpe_decision" not in text
```

- [ ] **Step 3: Run RED**

Run:

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py -q
```

Expected: FAIL because `_build_cpe_request_for_routing` does not exist and `RoutingService` does not yet import governance.

## Task 2: GREEN RoutingService CPE Request Builder

**Files:**
- Modify: `src/agentmind/services/routing_service.py`

- [ ] **Step 1: Add CPERequest import**

Add near existing imports:

```python
from agentmind.governance import CPERequest
```

- [ ] **Step 2: Add pure helper seam**

Add after `_get_app`:

```python
def _build_cpe_request_for_routing(
    *,
    trace_id: str,
    user_id: str,
    agent_id: str,
    message: str,
    agent_registry,
    memories: list[dict] | None = None,
) -> CPERequest:
    executor = agent_registry.get_executor(agent_id) if hasattr(agent_registry, "get_executor") else None
    if executor is None:
        executor = getattr(agent_registry, "executors", {}).get(agent_id)
    security_level = ""
    if executor is not None:
        security_level = getattr(getattr(executor, "capability", None), "security_level", "")
    return CPERequest(
        trace_id=trace_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_security_level=security_level,
        context={"message": message, "surface": "routing"},
        memory_items=memories or [],
    )
```

This helper is intentionally unused in live routing paths in this package.

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py -q
```

Expected: PASS.

## Task 3: Update Phase 5 Readiness

**Files:**
- Modify: `docs/phase5/phase-5-readiness.md`

- [ ] **Step 1: Record routing CPE seam**

Add a note under CPE start criteria:

```markdown
RoutingService has a CPE request-builder seam for routing context, but Phase 5 has not yet wired CPE decisions into routing behavior.
```

- [ ] **Step 2: Run focused readiness tests**

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused governance/routing tests**

```bash
pytest tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py tests/test_audit_service.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run routing-related regression**

```bash
pytest tests/test_router.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py tests/test_phase4_closure_audit.py tests/test_phase5_readiness_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest passes, diff check is clean, and status only shows this package before commit.

## Task 5: Commit

**Files:**
- `docs/superpowers/plans/2026-05-27-phase-5-cpe-routing-entrypoint-skeleton.md`
- `docs/phase5/phase-5-readiness.md`
- `src/agentmind/services/routing_service.py`
- `tests/test_cpe_routing_entrypoint.py`
- `tests/test_governance_skeleton.py`

- [ ] **Step 1: Commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-5-cpe-routing-entrypoint-skeleton.md docs/phase5/phase-5-readiness.md src/agentmind/services/routing_service.py tests/test_cpe_routing_entrypoint.py tests/test_governance_skeleton.py
git commit -m "feat: add cpe routing entrypoint skeleton"
```

## Self-Review

- Spec coverage: Covers only a service-level CPE request builder seam.
- Placeholder scan: No placeholders.
- Type consistency: Uses existing `CPERequest`.
