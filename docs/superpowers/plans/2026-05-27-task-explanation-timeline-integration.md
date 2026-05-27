# Task Explanation Timeline Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Include service-level task timelines in TaskExplanationService responses without adding replay, panel UI, or stream runtime behavior.

**Architecture:** TaskTimelineService owns task timeline DTO assembly. TaskExplanationService aggregates task lifecycle, routing explanation, audit events, and now timeline data for future adapters. Panel/API/channel remain unchanged in this package.

**Tech Stack:** Python service composition, pytest async tests, existing TaskExplanationService patterns.

---

## Scope

Modify:

- `src/agentmind/services/task_explanation_service.py`
- `tests/test_task_explanation_service.py`
- `docs/observability/task-event-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-task-explanation-timeline-integration.md`

Do not modify:

- panel/API/channel adapters
- TaskTimelineService DTO contract
- TaskEventService storage
- replay behavior
- stream runtime
- partial output capture

## Behavior

`TaskExplanationService.explain(trace_id)` should include:

```python
"timeline": await TaskTimelineService.timeline(trace_id)
```

For missing tasks, it should include:

```python
"timeline": {
    "trace_id": trace_id,
    "found": False,
    "event_count": 0,
    "timeline": [],
}
```

## Task 1: RED TaskExplanation Timeline Tests

**Files:**

- Modify: `tests/test_task_explanation_service.py`

- [ ] **Step 1: Add fake timeline service**

Add:

```python
class _TaskTimelineService:
    def __init__(self):
        self.calls = []

    async def timeline(self, trace_id):
        self.calls.append(trace_id)
        if trace_id == "missing":
            return {
                "trace_id": trace_id,
                "found": False,
                "event_count": 0,
                "timeline": [],
            }
        return {
            "trace_id": trace_id,
            "found": True,
            "event_count": 2,
            "timeline": [
                {"event_type": "task_started", "seq": 10},
                {"event_type": "failed", "seq": 90},
            ],
        }
```

- [ ] **Step 2: Inject timeline service in existing tests**

Pass `task_timeline_service=timeline_service` to `TaskExplanationService(...)` and assert:

```python
assert explanation["timeline"]["event_count"] == 2
assert explanation["timeline"]["timeline"] == [
    {"event_type": "task_started", "seq": 10},
    {"event_type": "failed", "seq": 90},
]
assert timeline_service.calls == ["t1"]
```

For missing task, assert the stable empty timeline is present.

- [ ] **Step 3: Run RED**

```bash
pytest tests/test_task_explanation_service.py -q
```

Expected: FAIL because `TaskExplanationService.__init__` does not accept `task_timeline_service`.

## Task 2: GREEN Service Integration

**Files:**

- Modify: `src/agentmind/services/task_explanation_service.py`

- [ ] **Step 1: Import and inject TaskTimelineService**

Add `from agentmind.services.task_timeline_service import TaskTimelineService`.

Add `task_timeline_service=None` to `__init__` and assign `self._task_timeline_service`.

- [ ] **Step 2: Include timeline in found and missing responses**

In `explain`, add `"timeline": await self._task_timeline_service.timeline(trace_id)`.

In `_missing`, add the stable empty timeline shape.

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_task_explanation_service.py -q
```

Expected: PASS.

## Task 3: Update Readiness Doc

**Files:**

- Modify: `docs/observability/task-event-readiness.md`

- [ ] **Step 1: Record explanation integration**

Add a note that TaskExplanationService includes TaskTimelineService timeline data at the service layer, while panel UI and replay remain out of scope.

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_task_explanation_service.py tests/test_task_timeline_service.py tests/test_observability_task_event_readiness.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run explanation focused tests**

```bash
pytest tests/test_task_explanation_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py tests/test_task_service.py -q
```

- [ ] **Step 2: Run service and panel explanation regression**

```bash
pytest tests/test_routing_explanation_service.py tests/test_audit_service.py tests/test_trace_service.py tests/test_panel_api.py -q
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
git add src/agentmind/services/task_explanation_service.py tests/test_task_explanation_service.py docs/observability/task-event-readiness.md docs/superpowers/plans/2026-05-27-task-explanation-timeline-integration.md
git commit -m "feat: include timeline in task explanations"
```
