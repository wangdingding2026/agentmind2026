# Panel Task Explanation Adapter Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the panel task explanation endpoint remains a thin adapter that explicitly wires TaskTimelineService and transparently returns the service response.

**Architecture:** TaskExplanationService owns task explanation aggregation. TaskTimelineService owns timeline DTO assembly. Panel should only construct service dependencies and return `service.explain(trace_id)`, without assembling timeline data or adding UI behavior.

**Tech Stack:** FastAPI TestClient, pytest panel adapter tests, existing panel service injection pattern.

---

## Scope

Modify:

- `src/agentmind/panel/server.py`
- `tests/test_panel_api.py`
- `docs/observability/task-event-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-panel-task-explanation-adapter-audit.md`

Do not modify:

- frontend UI
- TaskExplanationService behavior
- TaskTimelineService behavior
- TaskEventService storage
- replay behavior
- stream runtime

## Behavior

Panel endpoint `/panel/api/tasks/{trace_id}/explanation` should:

- instantiate `TaskExplanationService` with `task_service`, `routing_explanation_service`, `audit_service`, and `task_timeline_service`;
- call `service.explain(trace_id)`;
- return the service response as-is, including `timeline`;
- not assemble timeline data in panel code.

## Task 1: RED Panel Adapter Test

**Files:**

- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Extend fake service constructor**

In `test_task_explanation_endpoint_uses_service`, change `FakeTaskExplanationService.__init__` to accept `task_timeline_service=None`, record it in calls, and return a response containing timeline:

```python
class FakeTaskExplanationService:
    def __init__(
        self,
        *,
        task_service=None,
        routing_explanation_service=None,
        audit_service=None,
        task_timeline_service=None,
    ):
        calls.append({
            "task_service": task_service,
            "routing_explanation_service": routing_explanation_service,
            "audit_service": audit_service,
            "task_timeline_service": task_timeline_service,
        })

    async def explain(self, trace_id):
        calls.append({"trace_id": trace_id})
        return {
            "trace_id": trace_id,
            "found": True,
            "status": "failed",
            "stage": "execution",
            "timeline": {"trace_id": trace_id, "found": True, "event_count": 1, "timeline": []},
        }
```

Update response and dependency assertions:

```python
assert resp.json()["timeline"] == {
    "trace_id": "t1",
    "found": True,
    "event_count": 1,
    "timeline": [],
}
assert calls[0]["task_timeline_service"] is not None
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service -q
```

Expected: FAIL because panel does not yet pass `task_timeline_service`.

## Task 2: GREEN Panel Adapter Wiring

**Files:**

- Modify: `src/agentmind/panel/server.py`

- [ ] **Step 1: Import TaskTimelineService**

Add:

```python
from agentmind.services.task_timeline_service import TaskTimelineService
```

- [ ] **Step 2: Pass service dependency**

In `task_explanation`, pass:

```python
task_timeline_service=TaskTimelineService(),
```

- [ ] **Step 3: Run GREEN focused test**

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service -q
```

Expected: PASS.

## Task 3: Update Readiness Doc

**Files:**

- Modify: `docs/observability/task-event-readiness.md`

- [ ] **Step 1: Record adapter audit**

Add a note that the panel task explanation endpoint explicitly wires TaskTimelineService and returns service output, while UI rendering remains out of scope.

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service tests/test_task_explanation_service.py tests/test_task_timeline_service.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run panel/explanation focused tests**

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service tests/test_task_explanation_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

- [ ] **Step 2: Run panel and closure regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_observability_task_event_readiness.py tests/test_phase5_closure_audit.py -q
```

- [ ] **Step 3: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 4: Run full verification**

```bash
pytest -q
git diff --check
git status --short
```

## Task 5: Commit

**Files:**

- Commit all changed files.

- [ ] **Step 1: Commit**

```bash
git add src/agentmind/panel/server.py tests/test_panel_api.py docs/observability/task-event-readiness.md docs/superpowers/plans/2026-05-27-panel-task-explanation-adapter-audit.md
git commit -m "refactor: wire task timeline into panel explanation adapter"
```
