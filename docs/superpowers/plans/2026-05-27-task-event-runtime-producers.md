# Task Event Runtime Producers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce key task timeline events from the TaskService lifecycle seam without adding replay, UI, partial-output capture, or stream runtime changes.

**Architecture:** TaskService remains the task lifecycle owner and becomes the only producer added in this package. Existing routing/executor code already calls storage compatibility functions that delegate to TaskService, so runtime timeline production can be added at the service boundary without changing panel/API/channel adapters or stream internals.

**Tech Stack:** Python async service composition, TaskEventService, pytest monkeypatch/fake service tests.

---

## Scope

Modify:

- `src/agentmind/services/task_service.py`
- `tests/test_task_service.py`
- `docs/observability/task-event-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-task-event-runtime-producers.md`

Do not modify:

- RoutingService
- SingleAgentExecutor or SelfReplyExecutor
- stream_snapshot
- live SSE behavior
- panel/API/channel adapters
- TaskEventService storage schema
- replay behavior
- observability UI
- partial output capture

## Event Mapping

TaskService should emit:

- `start_task(...)` -> `task_started`, `seq=10`
- `update_task(..., status="routing", matched_rule=None, routed_agent=None)` -> `routing_started`, `seq=20`
- `update_task(..., status="routing", routed_agent=...)` -> `agent_selected`, `seq=30`
- `update_task(..., status="executing", ...)` -> `execution_started`, `seq=40`
- `end_task(..., status="completed", ...)` -> `completed`, `seq=90`
- `end_task(..., status="failed", ...)` -> `failed`, `seq=90`

Event production failures must not break task lifecycle persistence.

## Task 1: RED TaskService Producer Tests

**Files:**

- Modify: `tests/test_task_service.py`

- [ ] **Step 1: Add fake task event service and tests**

Append:

```python
class _TaskEventRecorder:
    def __init__(self):
        self.events = []

    async def record_event(self, **kwargs):
        self.events.append(kwargs)
        return f"event-{len(self.events)}"


class _FailingTaskEventRecorder:
    async def record_event(self, **kwargs):
        raise RuntimeError("event store unavailable")


@pytest.mark.asyncio
async def test_task_service_produces_timeline_events(tmp_db):
    event_service = _TaskEventRecorder()
    service = TaskService(task_event_service=event_service)

    await service.start_task("tr-events", "hello")
    await service.mark_routing("tr-events")
    await service.mark_routing("tr-events", matched_rule="rule", routed_agent="agent-a")
    await service.mark_executing("tr-events", routed_agent="agent-a")
    await service.complete_task("tr-events", "agent-a", result="done", execution_time_ms=12)

    assert [(event["event_type"], event["seq"]) for event in event_service.events] == [
        ("task_started", 10),
        ("routing_started", 20),
        ("agent_selected", 30),
        ("execution_started", 40),
        ("completed", 90),
    ]
    assert event_service.events[0]["message"] == "task started"
    assert event_service.events[0]["payload"] == {"user_message_length": 5}
    assert event_service.events[2]["agent_id"] == "agent-a"
    assert event_service.events[2]["payload"] == {"matched_rule": "rule"}
    assert event_service.events[3]["agent_id"] == "agent-a"
    assert event_service.events[4]["agent_id"] == "agent-a"
    assert event_service.events[4]["payload"] == {"execution_time_ms": 12}


@pytest.mark.asyncio
async def test_task_service_produces_failed_timeline_event(tmp_db):
    event_service = _TaskEventRecorder()
    service = TaskService(task_event_service=event_service)

    await service.start_task("tr-failed-events", "hello")
    await service.fail_task("tr-failed-events", "agent-a", error_message="boom", execution_time_ms=4)

    assert event_service.events[-1]["event_type"] == "failed"
    assert event_service.events[-1]["seq"] == 90
    assert event_service.events[-1]["agent_id"] == "agent-a"
    assert event_service.events[-1]["payload"] == {
        "execution_time_ms": 4,
        "has_error": True,
    }


@pytest.mark.asyncio
async def test_task_service_ignores_task_event_production_failures(tmp_db):
    service = TaskService(task_event_service=_FailingTaskEventRecorder())

    await service.start_task("tr-event-failure", "hello")
    await service.complete_task("tr-event-failure", "agent-a", result="done")

    detail = await service.get_task_detail("tr-event-failure")
    assert detail["status"] == "completed"
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_task_service.py::test_task_service_produces_timeline_events tests/test_task_service.py::test_task_service_produces_failed_timeline_event tests/test_task_service.py::test_task_service_ignores_task_event_production_failures -q
```

Expected: FAIL because `TaskService.__init__` does not accept `task_event_service`.

## Task 2: GREEN TaskService Producers

**Files:**

- Modify: `src/agentmind/services/task_service.py`

- [ ] **Step 1: Add TaskEventService dependency and helper**

Add:

```python
import logging

from agentmind.services.task_event_service import TaskEventService

logger = logging.getLogger("agentmind")
```

Add `__init__(self, task_event_service=None)` and a private `_record_task_event(...)` helper that catches exceptions.

- [ ] **Step 2: Emit lifecycle events**

Call `_record_task_event` after existing storage writes in `start_task`, `update_task`, and `end_task`.

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_task_service.py::test_task_service_produces_timeline_events tests/test_task_service.py::test_task_service_produces_failed_timeline_event tests/test_task_service.py::test_task_service_ignores_task_event_production_failures -q
```

Expected: PASS.

## Task 3: Update Readiness Doc

**Files:**

- Modify: `docs/observability/task-event-readiness.md`

- [ ] **Step 1: Record runtime producer status**

Add a section noting TaskService now produces lifecycle task events, while partial output, replay, UI, stream runtime, and panel/API/channel timeline assembly remain out of scope.

- [ ] **Step 2: Run focused tests**

```bash
pytest tests/test_task_service.py tests/test_task_event_service.py tests/test_observability_task_event_readiness.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run observability focused tests**

```bash
pytest tests/test_task_service.py tests/test_task_event_service.py tests/test_observability_task_event_readiness.py tests/test_phase5_closure_audit.py -q
```

- [ ] **Step 2: Run service and governance regression**

```bash
pytest tests/test_audit_service.py tests/test_trace_service.py tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py -q
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
git add src/agentmind/services/task_service.py tests/test_task_service.py docs/observability/task-event-readiness.md docs/superpowers/plans/2026-05-27-task-event-runtime-producers.md
git commit -m "feat: record task lifecycle events"
```
