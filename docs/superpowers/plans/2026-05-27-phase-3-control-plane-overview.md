# AgentMind Phase 3 Control Plane Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-owned control-plane overview so the panel can explain system status through one backend service boundary.

**Architecture:** `ControlPlaneOverviewService` is the service-layer aggregation boundary for system health and status. It composes `TaskService`, `AgentCapabilityRegistry`, `StrategyManager`, and `AuditService`; it does not execute routing rules or redefine strategy behavior. The panel router delegates `/service/status` and a new `/control/overview` endpoint to this service while preserving existing response shapes.

**Tech Stack:** Python 3.12, FastAPI APIRouter, existing local services, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `TaskService` owns task stats and metrics reads.
  - `AgentCapabilityRegistry` owns agent capability and runtime-health profiles.
  - `StrategyManager` owns strategy status and enablement.
  - `AuditService` owns audit filtering.
  - `ControlPlaneOverviewService` owns overview aggregation and status summaries.
- Rule/core layer owns rules:
  - `StrategyManager` exposes strategy state from the routing strategy layer.
  - Overview reports strategy status; it does not score, reorder, or execute routing rules.
- Panel layer stays thin:
  - Builds dependencies from `app.state`.
  - Returns service output.
  - Does not count agents or infer status directly for overview/status endpoints.

Transition compatibility:

- Existing `/panel/api/service/status` response shape remains unchanged.
- Existing `/panel/api/service/metrics` remains unchanged.
- New `/panel/api/control/overview` exposes richer control-plane status for future UI.
- No static front-end changes in this package.

Not allowed:

- SQL queries in panel endpoints.
- Business aggregation in `panel/server.py`.
- Rule/strategy execution inside overview service.
- ChannelHub or Phase 4 channel redesign.

Out of scope:

- Front-end UI rendering.
- Memory quality scoring.
- Security policy explanation.
- Evolution metrics.

## Files

Create:

- `src/agentmind/services/control_plane_overview_service.py`
- `tests/test_control_plane_overview_service.py`
- `docs/superpowers/plans/2026-05-27-phase-3-control-plane-overview.md`

Modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/services/__init__.py`
- `tests/test_panel_api.py`

## Overview Shape

```python
{
    "status": "degraded",
    "summary": {
        "agents_total": 2,
        "agents_healthy": 1,
        "tasks_total": 10,
        "tasks_completed": 8,
        "tasks_failed": 2,
        "avg_execution_time_ms": 42,
        "recent_audit_events": 1,
    },
    "agents": [{"agent_id": "a1", "healthy": True}],
    "strategies": [{"name": "explicit", "enabled": True}],
    "recent_errors": [{"trace_id": "t-fail"}],
    "recent_audit_events": [{"event_id": "e1"}],
}
```

Status mapping:

- `healthy`: at least one agent exists, all agents healthy, no failed tasks in stats.
- `degraded`: at least one agent is unhealthy or failed tasks exist.
- `empty`: no agents exist.

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_control_plane_overview_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_control_overview_endpoint_uses_service -q
pytest tests/test_panel_api.py::TestPanelAPI::test_service_status_uses_control_plane_overview_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_task_service.py tests/test_capability_registry.py tests/test_strategy_manager.py tests/test_audit_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: ControlPlaneOverviewService

**Files:**

- Create: `src/agentmind/services/control_plane_overview_service.py`
- Create: `tests/test_control_plane_overview_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- degraded overview when an agent is unhealthy and failed tasks exist.
- service-status compatibility projection from overview.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_control_plane_overview_service.py -q
```

Expected: FAIL because `ControlPlaneOverviewService` does not exist.

- [ ] **Step 3: Implement minimal service**

Create:

```python
class ControlPlaneOverviewService:
    def __init__(self, task_service=None, capability_registry=None, strategy_manager=None, audit_service=None):
        ...

    async def overview(self) -> dict:
        ...

    async def service_status(self) -> dict:
        ...
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_control_plane_overview_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Overview Endpoint

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel endpoint test**

Add `TestPanelAPI::test_control_overview_endpoint_uses_service` that monkeypatches `agentmind.panel.server.ControlPlaneOverviewService`, calls:

```text
GET /panel/api/control/overview
```

and asserts:

- Status is 200.
- Response is the service overview.
- Service constructor receives task, capability, strategy, and audit dependencies.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_control_overview_endpoint_uses_service -q
```

Expected: FAIL with 404 because endpoint does not exist.

- [ ] **Step 3: Implement thin endpoint**

In `panel/server.py`:

- Import `ControlPlaneOverviewService`.
- Add helper `_control_plane_overview_service(request)`.
- Add `GET /control/overview`.
- Return `await service.overview()`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_control_overview_endpoint_uses_service -q
```

Expected: PASS.

---

### Task 3: Move Service Status Aggregation To Overview Service

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED service-status delegation test**

Add `TestPanelAPI::test_service_status_uses_control_plane_overview_service` that monkeypatches `ControlPlaneOverviewService` and asserts `/service/status` returns `service.service_status()`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_service_status_uses_control_plane_overview_service -q
```

Expected: FAIL because `/service/status` still performs local aggregation.

- [ ] **Step 3: Implement delegation**

Replace local `/service/status` aggregation with:

```python
return await _control_plane_overview_service(request).service_status()
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_service_status_uses_control_plane_overview_service -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_control_plane_overview_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_control_overview_endpoint_uses_service -q
pytest tests/test_panel_api.py::TestPanelAPI::test_service_status_uses_control_plane_overview_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_task_service.py tests/test_capability_registry.py tests/test_strategy_manager.py tests/test_audit_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-control-plane-overview.md src/agentmind/services/control_plane_overview_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py tests/test_control_plane_overview_service.py tests/test_panel_api.py
git commit -m "feat: add control plane overview"
```
