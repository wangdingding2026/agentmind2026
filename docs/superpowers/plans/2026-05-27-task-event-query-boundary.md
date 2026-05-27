# Task Event Query Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-level task timeline query boundary over TaskEventService without adding replay, panel UI, or runtime behavior.

**Architecture:** TaskEventService owns persisted task events. TaskTimelineService owns read-side timeline DTO assembly for future replay or panel adapters. TaskExplanationService remains unchanged in this package; panel/API/channel do not call the new boundary yet.

**Tech Stack:** Python service composition, pytest async tests, existing service export pattern.

---

## Scope

Create:

- `src/agentmind/services/task_timeline_service.py`
- `tests/test_task_timeline_service.py`
- `docs/superpowers/plans/2026-05-27-task-event-query-boundary.md`

Modify:

- `src/agentmind/services/__init__.py`
- `docs/observability/task-event-readiness.md`

Do not modify:

- TaskEventService storage schema
- TaskService producers
- TaskExplanationService
- panel/API/channel adapters
- replay behavior
- stream runtime
- partial output capture

## DTO Contract

`TaskTimelineService.timeline(trace_id)` returns:

```python
{
    "trace_id": trace_id,
    "found": bool,
    "event_count": int,
    "timeline": [
        {
            "event_id": str,
            "created_at": str,
            "event_type": str,
            "seq": int,
            "agent_id": str,
            "message": str,
            "payload": dict,
        }
    ],
}
```

For no events:

```python
{
    "trace_id": trace_id,
    "found": False,
    "event_count": 0,
    "timeline": [],
}
```

## Task 1: RED Timeline Service Tests

**Files:**

- Create: `tests/test_task_timeline_service.py`

- [ ] **Step 1: Add service tests**

Create:

```python
import pytest


class _TaskEventService:
    def __init__(self):
        self.calls = []

    async def query_events(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["trace_id"] == "missing":
            return []
        return [
            {
                "event_id": "e1",
                "created_at": "2026-05-27 10:00:00",
                "trace_id": kwargs["trace_id"],
                "event_type": "task_started",
                "seq": 10,
                "agent_id": "",
                "message": "task started",
                "payload": {"user_message_length": 5},
            },
            {
                "event_id": "e2",
                "created_at": "2026-05-27 10:00:01",
                "trace_id": kwargs["trace_id"],
                "event_type": "completed",
                "seq": 90,
                "agent_id": "a1",
                "message": "",
                "payload": {"execution_time_ms": 12},
            },
        ]


@pytest.mark.asyncio
async def test_task_timeline_service_returns_stable_timeline_dto():
    from agentmind.services.task_timeline_service import TaskTimelineService

    task_event_service = _TaskEventService()
    service = TaskTimelineService(task_event_service=task_event_service)

    timeline = await service.timeline("t1")

    assert timeline == {
        "trace_id": "t1",
        "found": True,
        "event_count": 2,
        "timeline": [
            {
                "event_id": "e1",
                "created_at": "2026-05-27 10:00:00",
                "event_type": "task_started",
                "seq": 10,
                "agent_id": "",
                "message": "task started",
                "payload": {"user_message_length": 5},
            },
            {
                "event_id": "e2",
                "created_at": "2026-05-27 10:00:01",
                "event_type": "completed",
                "seq": 90,
                "agent_id": "a1",
                "message": "",
                "payload": {"execution_time_ms": 12},
            },
        ],
    }
    assert task_event_service.calls == [{"trace_id": "t1", "limit": 100}]


@pytest.mark.asyncio
async def test_task_timeline_service_returns_stable_missing_timeline():
    from agentmind.services.task_timeline_service import TaskTimelineService

    service = TaskTimelineService(task_event_service=_TaskEventService())

    assert await service.timeline("missing") == {
        "trace_id": "missing",
        "found": False,
        "event_count": 0,
        "timeline": [],
    }


def test_task_timeline_service_is_exported_from_services_package():
    from agentmind.services import TaskTimelineService

    assert TaskTimelineService.__name__ == "TaskTimelineService"
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_task_timeline_service.py -q
```

Expected: FAIL because `agentmind.services.task_timeline_service` does not exist.

## Task 2: GREEN Timeline Service

**Files:**

- Create: `src/agentmind/services/task_timeline_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Implement TaskTimelineService**

Create a service that calls `TaskEventService.query_events(trace_id=trace_id, limit=limit)` and normalizes each event to the DTO fields.

- [ ] **Step 2: Export TaskTimelineService**

Add the service to `src/agentmind/services/__init__.py`.

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_task_timeline_service.py -q
```

Expected: PASS.

## Task 3: Update Readiness Doc

**Files:**

- Modify: `docs/observability/task-event-readiness.md`

- [ ] **Step 1: Record query boundary**

Add a note that TaskTimelineService owns service-level task timeline DTO assembly, while replay and UI remain out of scope.

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_task_timeline_service.py tests/test_task_event_service.py tests/test_observability_task_event_readiness.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run observability focused tests**

```bash
pytest tests/test_task_timeline_service.py tests/test_task_event_service.py tests/test_task_service.py tests/test_observability_task_event_readiness.py -q
```

- [ ] **Step 2: Run service and explanation regression**

```bash
pytest tests/test_task_explanation_service.py tests/test_routing_explanation_service.py tests/test_audit_service.py tests/test_trace_service.py -q
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
git add src/agentmind/services/task_timeline_service.py src/agentmind/services/__init__.py tests/test_task_timeline_service.py docs/observability/task-event-readiness.md docs/superpowers/plans/2026-05-27-task-event-query-boundary.md
git commit -m "feat: add task timeline query boundary"
```
