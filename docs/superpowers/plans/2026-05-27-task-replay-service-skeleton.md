# Task Replay Service Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal service-level TaskReplayService skeleton over TaskTimelineService without wiring replay into panel/API/channel or stream runtime.

**Architecture:** TaskEventService owns stored task timeline events. TaskTimelineService owns read-side timeline DTO assembly. TaskReplayService introduces the future replay orchestration boundary by returning a stable service DTO over TaskTimelineService, but it does not replay SSE queues, mutate runtime streams, or expose adapter endpoints.

**Tech Stack:** Python async service class, pytest async tests, existing AgentMind service package exports, Markdown observability readiness docs.

---

## Scope

Create:

- `src/agentmind/services/task_replay_service.py`
- `tests/test_task_replay_service.py`
- `docs/superpowers/plans/2026-05-27-task-replay-service-skeleton.md`

Modify:

- `src/agentmind/services/__init__.py`
- `docs/observability/task-event-replay-readiness.md`

Do not modify:

- `src/agentmind/panel/server.py`
- API routes
- channel adapters
- stream runtime
- `SessionRuntimeService`
- `TaskEventService` storage behavior
- frontend UI

## Behavior

`TaskReplayService.replay(trace_id, limit=100)` should:

- call `TaskTimelineService.timeline(trace_id, limit=limit)`;
- return a stable DTO:

```python
{
    "trace_id": "t1",
    "found": True,
    "event_count": 2,
    "source": "task_events",
    "replay_status": "available",
    "timeline": [...],
}
```

- return `replay_status: "missing"` when the timeline is not found;
- preserve the timeline DTO events as provided by TaskTimelineService;
- not access stream queues, SSE listeners, panel request state, channel adapters, CPE, or AgentShield.

## Task 1: RED TaskReplayService Tests

**Files:**

- Create: `tests/test_task_replay_service.py`

- [ ] **Step 1: Add failing service tests**

Create `tests/test_task_replay_service.py`:

```python
import pytest


class _TaskTimelineService:
    def __init__(self):
        self.calls = []

    async def timeline(self, trace_id, limit=100):
        self.calls.append({"trace_id": trace_id, "limit": limit})
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
                {
                    "event_id": "e1",
                    "created_at": "2026-05-27 10:00:00",
                    "event_type": "task_started",
                    "seq": 10,
                    "agent_id": "",
                    "message": "task started",
                    "payload": {},
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


@pytest.mark.asyncio
async def test_task_replay_service_returns_service_level_replay_dto():
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _TaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    replay = await service.replay("t1", limit=25)

    assert replay == {
        "trace_id": "t1",
        "found": True,
        "event_count": 2,
        "source": "task_events",
        "replay_status": "available",
        "timeline": [
            {
                "event_id": "e1",
                "created_at": "2026-05-27 10:00:00",
                "event_type": "task_started",
                "seq": 10,
                "agent_id": "",
                "message": "task started",
                "payload": {},
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
    assert timeline_service.calls == [{"trace_id": "t1", "limit": 25}]


@pytest.mark.asyncio
async def test_task_replay_service_returns_missing_replay_dto():
    from agentmind.services.task_replay_service import TaskReplayService

    service = TaskReplayService(task_timeline_service=_TaskTimelineService())

    assert await service.replay("missing") == {
        "trace_id": "missing",
        "found": False,
        "event_count": 0,
        "source": "task_events",
        "replay_status": "missing",
        "timeline": [],
    }


def test_task_replay_service_is_exported_from_services_package():
    from agentmind.services import TaskReplayService

    assert TaskReplayService.__name__ == "TaskReplayService"
```

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_task_replay_service.py -q
```

Expected: FAIL because `agentmind.services.task_replay_service` does not exist.

## Task 2: GREEN TaskReplayService Skeleton

**Files:**

- Create: `src/agentmind/services/task_replay_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Create service skeleton**

Create `src/agentmind/services/task_replay_service.py`:

```python
from __future__ import annotations

from typing import Any

from agentmind.services.task_timeline_service import TaskTimelineService


class TaskReplayService:
    """Service-level replay boundary over persisted task timeline events."""

    def __init__(self, *, task_timeline_service=None):
        self._task_timeline_service = task_timeline_service or TaskTimelineService()

    async def replay(self, trace_id: str, limit: int = 100) -> dict[str, Any]:
        timeline = await self._task_timeline_service.timeline(
            trace_id,
            limit=limit,
        )
        found = bool(timeline.get("found"))
        return {
            "trace_id": timeline.get("trace_id", trace_id),
            "found": found,
            "event_count": timeline.get("event_count", 0),
            "source": "task_events",
            "replay_status": "available" if found else "missing",
            "timeline": timeline.get("timeline", []),
        }
```

- [ ] **Step 2: Export service**

Update `src/agentmind/services/__init__.py`:

```python
from agentmind.services.task_replay_service import TaskReplayService
```

Add `"TaskReplayService"` to `__all__`.

- [ ] **Step 3: Run GREEN focused test**

```bash
pytest tests/test_task_replay_service.py -q
```

Expected: PASS.

## Task 3: Update Replay Readiness

**Files:**

- Modify: `docs/observability/task-event-replay-readiness.md`

- [ ] **Step 1: Record skeleton status**

Add this under `## Existing Boundaries`:

```markdown
TaskReplayService owns the service-level replay DTO boundary over TaskTimelineService.
```

Add this under `## Explicit Non-Goals`:

```markdown
- no panel/API/channel TaskReplayService adapters in this package;
```

Update `## Next Direction` to:

```markdown
After this skeleton remains green, the next package can add service-level replay contract hardening around event limits and stable ordering. Panel UI and stream runtime changes remain out of scope until the service contract is proven.
```

- [ ] **Step 2: Run focused service and readiness tests**

```bash
pytest tests/test_task_replay_service.py tests/test_task_event_replay_readiness.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

Expected: PASS.

## Task 4: Regression Verification

**Files:**

- No additional edits expected.

- [ ] **Step 1: Run observability/service focused tests**

```bash
pytest tests/test_task_replay_service.py tests/test_task_event_replay_readiness.py tests/test_observability_task_event_readiness.py tests/test_task_event_service.py tests/test_task_timeline_service.py tests/test_task_explanation_service.py -q
```

- [ ] **Step 2: Run panel/architecture regression**

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py -q
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
git add src/agentmind/services/task_replay_service.py src/agentmind/services/__init__.py tests/test_task_replay_service.py docs/observability/task-event-replay-readiness.md docs/superpowers/plans/2026-05-27-task-replay-service-skeleton.md
git commit -m "feat: add task replay service skeleton"
```
