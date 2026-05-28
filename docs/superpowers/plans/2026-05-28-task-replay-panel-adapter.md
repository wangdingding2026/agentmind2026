# Task Replay Panel Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only panel TaskReplay adapter endpoint that returns the TaskReplayService DTO without adding API, channel, stream runtime, or UI replay behavior.

**Architecture:** `TaskReplayService` remains the service-level replay DTO boundary over `TaskTimelineService`. The panel handler only adapts HTTP path/query inputs to `TaskReplayService.replay(trace_id, limit=limit)` and returns the service response unchanged. Panel must not assemble timelines, query `TaskEventService`, call `TaskTimelineService`, touch stream queues, enable governance enforcement, or inspect customer content.

**Tech Stack:** FastAPI, pytest, Python service-layer tests, Markdown architecture docs.

---

## File Structure

- Modify: `tests/test_panel_api.py`
  - Adds RED/GREEN coverage for `/panel/api/tasks/{trace_id}/replay`.
  - Verifies the endpoint constructs `TaskReplayService`, calls `replay(trace_id, limit)`, and returns the service DTO unchanged.
- Modify: `src/agentmind/panel/server.py`
  - Imports `TaskReplayService`.
  - Adds `task_replay` panel route before the generic `/tasks/{trace_id}` route.
  - Handler only calls `TaskReplayService().replay(trace_id, limit=limit)`.
- Modify: `tests/test_panel_control_plane_boundary.py`
  - Adds `task_replay` to the service-backed handler inventory.
  - Adds forbidden direct replay patterns for service-backed panel handlers.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Documents `task_replay` as service-backed.
  - Adds replay-specific adapter constraints.
- Modify: `docs/observability/task-replay-adapter-readiness.md`
  - Records that the read-only panel replay adapter has been implemented.
- Modify: `tests/test_task_replay_adapter_readiness.py`
  - Updates adapter readiness markers from "no replay endpoint" to the implemented panel adapter state.

No API endpoint, channel adapter, stream runtime replay, observability UI, CPE/AgentShield enforcement, customer-content inspection, `TaskEventService` schema change, or `TaskTimelineService` query/order change is in scope.

### Task 1: Add Panel Replay Adapter RED Test

**Files:**
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write the failing test**

Add this test near `test_task_explanation_endpoint_uses_service` in `tests/test_panel_api.py`:

```python
    def test_task_replay_endpoint_uses_task_replay_service(self):
        calls = []

        class FakeTaskReplayService:
            def __init__(self):
                calls.append({"constructed": True})

            async def replay(self, trace_id, limit=100):
                calls.append({"trace_id": trace_id, "limit": limit})
                return {
                    "trace_id": trace_id,
                    "found": True,
                    "event_count": 1,
                    "source": "task_events",
                    "replay_status": "available",
                    "limit": limit,
                    "timeline": [
                        {
                            "event_id": "e1",
                            "created_at": "2026-05-28 10:00:00",
                            "event_type": "task_started",
                            "seq": 10,
                            "agent_id": "",
                            "message": "task started",
                            "payload": {},
                        }
                    ],
                }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            mp.setattr(
                "agentmind.panel.server.TaskReplayService",
                FakeTaskReplayService,
                raising=False,
            )
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/tasks/t1/replay?limit=25")
                assert resp.status_code == 200
                assert resp.json() == {
                    "trace_id": "t1",
                    "found": True,
                    "event_count": 1,
                    "source": "task_events",
                    "replay_status": "available",
                    "limit": 25,
                    "timeline": [
                        {
                            "event_id": "e1",
                            "created_at": "2026-05-28 10:00:00",
                            "event_type": "task_started",
                            "seq": 10,
                            "agent_id": "",
                            "message": "task started",
                            "payload": {},
                        }
                    ],
                }
                assert calls == [
                    {"constructed": True},
                    {"trace_id": "t1", "limit": 25},
                ]
            finally:
                mp.undo()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_replay_endpoint_uses_task_replay_service -q
```

Expected: FAIL with 404 or missing `TaskReplayService` attribute, because the panel replay route is not implemented yet.

### Task 2: Implement Minimal Panel Adapter

**Files:**
- Modify: `src/agentmind/panel/server.py`
- Test: `tests/test_panel_api.py`

- [ ] **Step 1: Import TaskReplayService**

Add the import near the other task service imports:

```python
from agentmind.services.task_replay_service import TaskReplayService
```

- [ ] **Step 2: Add route before `/tasks/{trace_id}`**

Add this handler after `task_explanation` and before `task_detail` so `replay` is not captured as a task detail trace id:

```python
    @router.get("/tasks/{trace_id}/replay")
    async def task_replay(trace_id: str, limit: int = 100):
        return await TaskReplayService().replay(trace_id, limit=limit)
```

- [ ] **Step 3: Run focused GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_replay_endpoint_uses_task_replay_service -q
```

Expected: PASS.

### Task 3: Harden Panel Boundary Audit

**Files:**
- Modify: `tests/test_panel_control_plane_boundary.py`
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/observability/task-replay-adapter-readiness.md`
- Modify: `tests/test_task_replay_adapter_readiness.py`

- [ ] **Step 1: Add `task_replay` to service-backed handler inventory**

In `tests/test_panel_control_plane_boundary.py`, add:

```python
    "task_replay",
```

to `SERVICE_BACKED_HANDLERS`.

- [ ] **Step 2: Add direct replay anti-patterns**

In `FORBIDDEN_SERVICE_BACKED_PATTERNS`, add:

```python
    "TaskEventService(": "replay adapters must not query task-event storage directly",
    "TaskTimelineService().timeline": "replay adapters must not assemble timeline DTOs",
    "stream_snapshot(": "replay adapters must not use stream backlog snapshots",
```

- [ ] **Step 3: Document the handler boundary**

In `docs/phase3/panel-control-plane-boundary.md`, add `task_replay` to the service-backed handler list and add this panel constraint:

```markdown
- assemble, replay, or query task replay timelines directly; panel replay adapters must call `TaskReplayService` and return its DTO.
```

- [ ] **Step 4: Update adapter readiness status**

In `docs/observability/task-replay-adapter-readiness.md`, replace:

```markdown
panel, API, and channel replay endpoints are not implemented in this package.
endpoint implementation requires a separate small package.
```

with:

```markdown
The read-only panel replay endpoint is implemented as an adapter in this package.

API and channel replay endpoints are not implemented in this package.
Additional endpoint implementation requires a separate small package.
```

Also replace:

```markdown
panel/API/channel currently have no replay endpoint.
```

with:

```markdown
The panel has a read-only replay endpoint backed by TaskReplayService.

API and channel currently have no replay endpoint.
```

Add this section before Explicit Non-Goals:

```markdown
## Implemented Panel Adapter

The panel `task_replay` handler calls TaskReplayService and returns the service DTO.

The panel adapter does not assemble timeline data, query TaskEventService, connect to stream queues, implement stream runtime replay, implement observability UI, enable CPE or AgentShield enforcement, or inspect customer content.
```

- [ ] **Step 5: Run focused panel tests**

Update `tests/test_task_replay_adapter_readiness.py` so the readiness markers require the implemented panel adapter state:

```python
    "The panel has a read-only replay endpoint backed by TaskReplayService",
    "API and channel currently have no replay endpoint",
    "The panel `task_replay` handler calls TaskReplayService",
```

Replace the old assertion for `"not implemented in this package"` with:

```python
    assert "The read-only panel replay endpoint is implemented" in text
    assert "Additional endpoint implementation requires a separate small package" in text
```

- [ ] **Step 6: Run focused panel tests**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_replay_endpoint_uses_task_replay_service tests/test_panel_control_plane_boundary.py -q
```

Expected: PASS.

### Task 4: Run Required Regression Gates

**Files:**
- Read: all modified files

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_task_replay_endpoint_uses_task_replay_service tests/test_panel_control_plane_boundary.py tests/test_task_replay_adapter_readiness.py -q
```

Expected: PASS.

- [ ] **Step 2: Run observability/service gate**

Run:

```bash
pytest tests/test_task_replay_adapter_readiness.py tests/test_task_event_replay_readiness.py tests/test_task_replay_service.py tests/test_task_timeline_service.py tests/test_task_event_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run panel/architecture gate**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase5_closure_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected: pytest PASS, diff check clean, status shows only intended changed files before commit.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/agentmind/panel/server.py tests/test_panel_api.py tests/test_panel_control_plane_boundary.py docs/phase3/panel-control-plane-boundary.md docs/observability/task-replay-adapter-readiness.md docs/superpowers/plans/2026-05-28-task-replay-panel-adapter.md
git commit -m "feat: add task replay panel adapter"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan implements only the read-only panel adapter approved by the adapter readiness gate.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Scope check: no API endpoint, channel adapter, stream runtime replay, observability UI, governance enforcement, customer-content inspection, old fallback expansion, `TaskEventService` schema change, or `TaskTimelineService` query/order change is included.
