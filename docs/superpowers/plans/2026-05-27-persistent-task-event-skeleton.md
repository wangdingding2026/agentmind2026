# Persistent Task Event Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the minimal TaskEventService storage contract for ordered task timeline events without wiring replay, UI, stream runtime, or routing behavior.

**Architecture:** TaskEventService owns task timeline events and persists them in the local trace database. TaskService still owns task lifecycle state, TraceService owns routing traces, and AuditService owns audit records. This package creates only the service/storage seam and event vocabulary.

**Tech Stack:** Python async service wrapper, SQLite, JSON payloads, pytest async tests.

---

## Scope

Create:

- `src/agentmind/services/task_event_service.py`
- `tests/test_task_event_service.py`
- `docs/superpowers/plans/2026-05-27-persistent-task-event-skeleton.md`

Modify:

- `src/agentmind/services/__init__.py`
- `docs/observability/task-event-readiness.md`

Do not modify:

- RoutingService
- TaskService lifecycle writes
- TraceService
- AuditService
- panel/API/channel adapters
- stream_snapshot or live SSE queues
- replay behavior
- UI behavior

## Event Contract

Allowed event types:

- `task_started`
- `routing_started`
- `agent_selected`
- `execution_started`
- `partial_output`
- `completed`
- `failed`

Task events must include:

- `event_id`
- `created_at`
- `trace_id`
- `event_type`
- `seq`
- `agent_id`
- `message`
- `payload`

Events are queried by `trace_id`, ordered by `seq` and creation order.

## Task 1: RED Service Tests

**Files:**

- Create: `tests/test_task_event_service.py`

- [ ] **Step 1: Add task event service tests**

Create:

```python
import json
import sqlite3

import pytest


@pytest.mark.asyncio
async def test_task_event_service_records_and_queries_ordered_events(tmp_path):
    from agentmind.services.task_event_service import TaskEventService

    service = TaskEventService(str(tmp_path / "trace.db"))

    first_id = await service.record_event(
        trace_id="t1",
        event_type="task_started",
        message="task started",
        payload={"source": "route"},
    )
    second_id = await service.record_event(
        trace_id="t1",
        event_type="agent_selected",
        seq=20,
        agent_id="a1",
        payload={"strategy": "explicit"},
    )
    await service.record_event(
        trace_id="t2",
        event_type="task_started",
        message="other task",
    )

    events = await service.query_events(trace_id="t1")

    assert [event["event_id"] for event in events] == [first_id, second_id]
    assert [event["event_type"] for event in events] == [
        "task_started",
        "agent_selected",
    ]
    assert events[0]["seq"] == 10
    assert events[0]["message"] == "task started"
    assert events[0]["payload"] == {"source": "route"}
    assert events[1]["seq"] == 20
    assert events[1]["agent_id"] == "a1"
    assert events[1]["payload"] == {"strategy": "explicit"}


@pytest.mark.asyncio
async def test_task_event_service_rejects_unknown_event_type(tmp_path):
    from agentmind.services.task_event_service import TaskEventService

    service = TaskEventService(str(tmp_path / "trace.db"))

    with pytest.raises(ValueError, match="unsupported task event type"):
        await service.record_event(trace_id="t1", event_type="unknown")


def test_task_events_are_persisted_as_json_payload(tmp_path):
    from agentmind.services.task_event_service import TaskEventService

    service = TaskEventService(str(tmp_path / "trace.db"))
    event_id = service._record_event_sync(
        trace_id="t1",
        event_type="partial_output",
        payload={"chunk_index": 1, "size": 42},
    )

    conn = sqlite3.connect(str(tmp_path / "trace.db"))
    try:
        row = conn.execute(
            "SELECT payload FROM task_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()

    assert json.loads(row[0]) == {"chunk_index": 1, "size": 42}


def test_task_event_service_is_exported_from_services_package():
    from agentmind.services import TaskEventService

    assert TaskEventService.__name__ == "TaskEventService"
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_task_event_service.py -q
```

Expected: FAIL because `agentmind.services.task_event_service` does not exist.

## Task 2: GREEN Service Implementation

**Files:**

- Create: `src/agentmind/services/task_event_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Add TaskEventService**

Create the service with:

- local SQLite table `task_events`;
- `record_event(...)`;
- `_record_event_sync(...)`;
- `query_events(trace_id=..., limit=100)`;
- `_query_events_sync(...)`;
- JSON payload formatting;
- event type validation.

- [ ] **Step 2: Export service**

Add `TaskEventService` to `src/agentmind/services/__init__.py`.

- [ ] **Step 3: Run GREEN focused tests**

```bash
pytest tests/test_task_event_service.py -q
```

Expected: PASS.

## Task 3: Update Readiness Doc

**Files:**

- Modify: `docs/observability/task-event-readiness.md`

- [ ] **Step 1: Record skeleton status**

Add a section noting that TaskEventService skeleton owns the local storage contract but is not yet wired into runtime production, replay, or UI.

- [ ] **Step 2: Run focused readiness tests**

```bash
pytest tests/test_task_event_service.py tests/test_observability_task_event_readiness.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run observability focused tests**

```bash
pytest tests/test_task_event_service.py tests/test_observability_task_event_readiness.py tests/test_phase5_closure_audit.py -q
```

- [ ] **Step 2: Run service and governance regression**

```bash
pytest tests/test_audit_service.py tests/test_trace_service.py tests/test_task_service.py tests/test_governance_skeleton.py tests/test_cpe_routing_entrypoint.py -q
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
git add src/agentmind/services/task_event_service.py src/agentmind/services/__init__.py tests/test_task_event_service.py docs/observability/task-event-readiness.md docs/superpowers/plans/2026-05-27-persistent-task-event-skeleton.md
git commit -m "feat: add task event service skeleton"
```
