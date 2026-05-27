# AgentMind Phase 3 Task Explanation API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-owned task explanation API so the control plane can explain where a task failed or completed.

**Architecture:** `TaskExplanationService` is the service-layer boundary for task explanation assembly. It reads task lifecycle state through `TaskService`, correlates routing context through `RoutingExplanationService`, and reads task-scoped audit events through `AuditService`. The panel router remains a thin adapter and does not inspect task fields to infer failure causes.

**Tech Stack:** Python 3.12, FastAPI APIRouter, existing local SQLite-backed services, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `TaskService` owns task lifecycle reads and writes.
  - `TaskExplanationService` owns task explanation aggregation.
  - `RoutingExplanationService` owns routing explanation aggregation.
  - `AuditService` owns audit query filtering.
- Rule/core layer owns rules:
  - Existing routing strategies and rule engine continue to decide route strategy, match rule, candidates, and confidence.
  - Task explanation only reports those outputs; it does not redefine routing rules.
- Panel layer stays thin:
  - Builds service dependencies from `app.state`.
  - Returns service output.
  - Does not directly query storage for explanation logic.

Transition compatibility:

- Existing `/panel/api/tasks/{trace_id}` response remains unchanged.
- Existing `/panel/api/routing/explanations/{trace_id}` remains unchanged.
- Existing panel task list/stats/recent-errors endpoints should begin using `TaskService` as the service boundary while preserving response shapes.

Not allowed:

- SQL queries in panel endpoints.
- Explanation inference inside `panel/server.py` or `api/router.py`.
- Changing routing strategies or rule-engine behavior in this package.
- Front-end/static UI changes.

Out of scope:

- Deep executor stack traces.
- Retrying failed tasks.
- ChannelHub or Phase 4 channel explanation.
- Security policy root-cause explanation.

## Files

Create:

- `src/agentmind/services/task_explanation_service.py`
- `tests/test_task_explanation_service.py`
- `docs/superpowers/plans/2026-05-27-phase-3-task-explanation-api.md`

Modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/services/__init__.py`
- `tests/test_panel_api.py`

## Explanation Shape

For a found failed task:

```python
{
    "trace_id": "t1",
    "found": True,
    "status": "failed",
    "failed": True,
    "stage": "execution",
    "summary": "Task failed during execution: timeout",
    "task": {"trace_id": "t1", "status": "failed", "error_message": "timeout"},
    "routing": {"trace_id": "t1", "found": True},
    "audit_events": [{"trace_id": "t1", "module": "routing"}],
}
```

For a missing task:

```python
{
    "trace_id": "missing",
    "found": False,
    "status": "missing",
    "failed": False,
    "stage": "unknown",
    "summary": "Task not found",
    "task": None,
    "routing": None,
    "audit_events": [],
}
```

Stage mapping:

- `pending`, `routing` -> `routing`
- `executing` -> `execution`
- `completed` -> `completed`
- `failed` with `routed_agent` -> `execution`
- `failed` without `routed_agent` -> `routing`
- any unknown status -> `unknown`

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_task_explanation_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_task_service.py tests/test_routing_explanation_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: TaskExplanationService

**Files:**

- Create: `src/agentmind/services/task_explanation_service.py`
- Create: `tests/test_task_explanation_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- failed task with routed agent is explained as an execution failure and includes routing/audit context.
- missing task returns a stable missing explanation.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_task_explanation_service.py -q
```

Expected: FAIL because `TaskExplanationService` does not exist.

- [ ] **Step 3: Implement minimal service**

Create:

```python
class TaskExplanationService:
    def __init__(self, task_service=None, routing_explanation_service=None, audit_service=None):
        ...

    async def explain(self, trace_id: str) -> dict:
        ...
```

The service should infer stage only from persisted task lifecycle fields and should not invoke routing rules.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_task_explanation_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Task Explanation Endpoint

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel endpoint test**

Add `TestPanelAPI::test_task_explanation_endpoint_uses_service` that monkeypatches `agentmind.panel.server.TaskExplanationService`, calls:

```text
GET /panel/api/tasks/t1/explanation
```

and asserts:

- Status is 200.
- Response is the service explanation.
- Service constructor receives `task_service`, `routing_explanation_service`, and `audit_service`.
- `explain()` receives `t1`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service -q
```

Expected: FAIL with 404 because endpoint does not exist.

- [ ] **Step 3: Implement thin endpoint**

In `panel/server.py`:

- Import `TaskExplanationService`, `TaskService`.
- Add helper constructors only to avoid duplicate dependency wiring.
- Add `GET /tasks/{trace_id}/explanation`.
- Return `await service.explain(trace_id)`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

### Task 3: Panel Task Reads Through TaskService

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Strengthen service-boundary tests**

Add or update panel tests to monkeypatch `TaskService` and verify task list/detail/stats/error endpoints use the service boundary.

- [ ] **Step 2: Implement service delegation**

Replace direct panel imports of storage task query functions with `TaskService()` calls while preserving response shapes.

- [ ] **Step 3: Verify panel regression**

Run:

```bash
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_task_explanation_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_task_explanation_endpoint_uses_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_task_service.py tests/test_routing_explanation_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-task-explanation-api.md src/agentmind/services/task_explanation_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py tests/test_task_explanation_service.py tests/test_panel_api.py
git commit -m "feat: add task explanation api"
```
