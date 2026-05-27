# Task Replay Service Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the TaskReplayService service-level DTO contract around limits, missing timeline fields, and ordering assumptions without adding adapter or stream replay behavior.

**Architecture:** TaskReplayService remains a service boundary over TaskTimelineService. It normalizes caller limits before querying timeline data, returns stable replay DTO fields even when timeline data is sparse, and preserves the event order produced by TaskTimelineService rather than sorting in adapters.

**Tech Stack:** Python async service class, pytest async tests, existing AgentMind observability readiness docs.

---

## Scope

Modify:

- `src/agentmind/services/task_replay_service.py`
- `tests/test_task_replay_service.py`
- `docs/observability/task-event-replay-readiness.md`

Create:

- `docs/superpowers/plans/2026-05-27-task-replay-service-contract-hardening.md`

Do not modify:

- panel routes
- API routes
- channel adapters
- stream runtime
- `SessionRuntimeService`
- `TaskEventService` storage schema
- `TaskTimelineService` ordering/query behavior
- frontend UI

## Behavior

`TaskReplayService.replay(trace_id, limit=100)` should:

- normalize `limit` to an integer between 1 and 500;
- use `100` when `limit` is invalid, non-numeric, or `None`;
- pass the normalized limit to `TaskTimelineService.timeline()`;
- return stable top-level fields:

```python
{
    "trace_id": "t1",
    "found": False,
    "event_count": 0,
    "source": "task_events",
    "replay_status": "missing",
    "limit": 100,
    "timeline": [],
}
```

- preserve timeline event order as returned by TaskTimelineService;
- not inspect payload content, not apply CPE/AgentShield, and not touch stream queues.

## Task 1: RED Contract Tests

**Files:**

- Modify: `tests/test_task_replay_service.py`

- [ ] **Step 1: Add sparse timeline fixture**

Add this helper class after `_TaskTimelineService`:

```python
class _SparseTaskTimelineService:
    def __init__(self):
        self.calls = []

    async def timeline(self, trace_id, limit=100):
        self.calls.append({"trace_id": trace_id, "limit": limit})
        return {"timeline": []}
```

- [ ] **Step 2: Update existing DTO expectations**

Add `"limit": 25` to the expected DTO in `test_task_replay_service_returns_service_level_replay_dto`.

Add `"limit": 100` to the expected DTO in `test_task_replay_service_returns_missing_replay_dto`.

- [ ] **Step 3: Add limit normalization test**

Add:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_limit", "expected_limit"),
    [
        (0, 1),
        (-5, 1),
        (501, 500),
        ("7", 7),
        ("bad", 100),
        (None, 100),
    ],
)
async def test_task_replay_service_normalizes_limit(input_limit, expected_limit):
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _TaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    replay = await service.replay("t1", limit=input_limit)

    assert replay["limit"] == expected_limit
    assert timeline_service.calls == [{"trace_id": "t1", "limit": expected_limit}]
```

- [ ] **Step 4: Add sparse DTO stability test**

Add:

```python
@pytest.mark.asyncio
async def test_task_replay_service_stabilizes_sparse_timeline_response():
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _SparseTaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    assert await service.replay("t1") == {
        "trace_id": "t1",
        "found": False,
        "event_count": 0,
        "source": "task_events",
        "replay_status": "missing",
        "limit": 100,
        "timeline": [],
    }
    assert timeline_service.calls == [{"trace_id": "t1", "limit": 100}]
```

- [ ] **Step 5: Add ordering preservation test**

Add:

```python
@pytest.mark.asyncio
async def test_task_replay_service_preserves_timeline_service_order():
    from agentmind.services.task_replay_service import TaskReplayService

    timeline_service = _TaskTimelineService()
    service = TaskReplayService(task_timeline_service=timeline_service)

    replay = await service.replay("t1")

    assert [event["event_id"] for event in replay["timeline"]] == ["e1", "e2"]
```

- [ ] **Step 6: Run RED**

```bash
pytest tests/test_task_replay_service.py -q
```

Expected: FAIL because TaskReplayService does not yet return `limit` and does not normalize caller limits.

## Task 2: GREEN Contract Implementation

**Files:**

- Modify: `src/agentmind/services/task_replay_service.py`

- [ ] **Step 1: Add limit normalization**

Update `TaskReplayService`:

```python
class TaskReplayService:
    """Service-level replay boundary over persisted task timeline events."""

    DEFAULT_LIMIT = 100
    MIN_LIMIT = 1
    MAX_LIMIT = 500

    def __init__(self, *, task_timeline_service=None):
        self._task_timeline_service = task_timeline_service or TaskTimelineService()

    async def replay(self, trace_id: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        normalized_limit = self._normalize_limit(limit)
        timeline = await self._task_timeline_service.timeline(
            trace_id,
            limit=normalized_limit,
        )
        found = bool(timeline.get("found"))
        return {
            "trace_id": timeline.get("trace_id") or trace_id,
            "found": found,
            "event_count": timeline.get("event_count") or 0,
            "source": "task_events",
            "replay_status": "available" if found else "missing",
            "limit": normalized_limit,
            "timeline": timeline.get("timeline") or [],
        }

    def _normalize_limit(self, limit) -> int:
        try:
            normalized = int(limit)
        except (TypeError, ValueError):
            normalized = self.DEFAULT_LIMIT
        return max(self.MIN_LIMIT, min(self.MAX_LIMIT, normalized))
```

- [ ] **Step 2: Run GREEN focused test**

```bash
pytest tests/test_task_replay_service.py -q
```

Expected: PASS.

## Task 3: Update Replay Readiness

**Files:**

- Modify: `docs/observability/task-event-replay-readiness.md`

- [ ] **Step 1: Record hardened contract**

Add under `## Existing Boundaries`:

```markdown
TaskReplayService normalizes replay limits at the service boundary, returns stable missing and found DTOs, and preserves TaskTimelineService event order.
```

Update `## Next Direction`:

```markdown
After this service contract remains green, the next package can decide whether a read-only panel/API adapter is needed. Stream runtime replay, observability UI, and channel replay remain out of scope until a separate adapter plan is approved.
```

- [ ] **Step 2: Run readiness focused tests**

```bash
pytest tests/test_task_replay_service.py tests/test_task_event_replay_readiness.py -q
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
git add src/agentmind/services/task_replay_service.py tests/test_task_replay_service.py docs/observability/task-event-replay-readiness.md docs/superpowers/plans/2026-05-27-task-replay-service-contract-hardening.md
git commit -m "refactor: harden task replay service contract"
```
