# Phase 4 Stream Resumability Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-backed stream snapshot/replay boundary for existing in-memory stream backlog while explicitly keeping live listener queues non-persistent.

**Architecture:** `SessionRegistry` remains the in-process runtime primitive for live SSE listeners and short stream backlog. `SessionRuntimeService` gains a read-only snapshot method that exposes replayable backlog and listener count without registering a queue. Panel streaming continues to use live SSE through `stream_events()`. This package does not write stream events to SQLite and does not restore queue objects after restart.

**Tech Stack:** Python, `SessionRegistry`, `SessionRuntimeService`, pytest, pytest-asyncio, Markdown architecture docs.

---

## Scope

Target in this package:

- Add `SessionRegistry.stream_snapshot(trace_id)` returning:
  - `trace_id`;
  - `backlog` as the current replayable backlog list;
  - `listener_count`;
  - `resumable` boolean indicating whether backlog exists.
- Add `SessionRuntimeService.stream_snapshot(trace_id)` as the service boundary for snapshot/replay metadata.
- Preserve existing live `stream_events(trace_id)` behavior:
  - it still registers a queue;
  - it still replays current backlog to the queue;
  - it still unregisters the queue in `finally`.
- Keep restart behavior explicit:
  - `restore_discussions()` clears `_streams`;
  - stream listener queues and backlog are not persisted or restored.
- Update architecture docs to say stream resumability is bounded to in-process backlog snapshots for this phase.

Out of scope:

- Do not persist stream events/backlog to SQLite.
- Do not restore live queue objects.
- Do not add a new panel HTTP endpoint in this package.
- Do not change `EventSourceResponse` behavior.
- Do not change routing pipeline or task event production.
- Do not change ChannelHub or Feishu behavior.
- Do not start Phase 5 CPE or AgentShield work.

## Files

- Modify: `src/agentmind/routing/side_effects/session_registry.py`
  - Add `stream_snapshot(trace_id)`.
- Modify: `src/agentmind/services/session_runtime_service.py`
  - Add `stream_snapshot(trace_id)` service method.
- Modify: `tests/test_stream.py`
  - Add RED/GREEN coverage for snapshot metadata, backlog copy safety, and non-persistence on restore.
- Modify: `tests/test_session_runtime_service.py`
  - Add RED/GREEN coverage that service exposes stream snapshot without registering listeners.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Record that stream resumability is an in-process snapshot boundary and live queues remain volatile.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Record this Phase 4 package and next migration direction.

## Tasks

### Task 1: RED StreamRegistry Snapshot Boundary

**Files:**
- Modify: `tests/test_stream.py`

- [ ] **Step 1: Add failing stream snapshot test**

Add under `TestStreamRegistry`:

```python
    def test_stream_snapshot_returns_backlog_without_registering_listener(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()
        sr.broadcast_stream_chunk("tr-snap", {"event": "partial", "data": "one"})
        sr.broadcast_stream_chunk("tr-snap", {"event": "partial", "data": "two"})

        snapshot = sr.stream_snapshot("tr-snap")

        assert snapshot == {
            "trace_id": "tr-snap",
            "backlog": [
                {"event": "partial", "data": "one"},
                {"event": "partial", "data": "two"},
            ],
            "listener_count": 0,
            "resumable": True,
        }
        assert sr._streams["tr-snap"]["listeners"] == []
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_stream.py::TestStreamRegistry::test_stream_snapshot_returns_backlog_without_registering_listener -q
```

Expected: FAIL because `SessionRegistry` has no `stream_snapshot()`.

### Task 2: GREEN StreamRegistry Snapshot

**Files:**
- Modify: `src/agentmind/routing/side_effects/session_registry.py`

- [ ] **Step 1: Add snapshot method**

Add:

```python
    def stream_snapshot(self, trace_id: str) -> dict:
        registry = self._streams.get(trace_id)
        if not registry:
            return {
                "trace_id": trace_id,
                "backlog": [],
                "listener_count": 0,
                "resumable": False,
            }
        backlog = list(registry.get("backlog", []))
        return {
            "trace_id": trace_id,
            "backlog": backlog,
            "listener_count": len(registry.get("listeners", [])),
            "resumable": bool(backlog),
        }
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_stream.py::TestStreamRegistry::test_stream_snapshot_returns_backlog_without_registering_listener -q
```

Expected: 1 passed.

### Task 3: RED Snapshot Missing Trace And Restore Semantics

**Files:**
- Modify: `tests/test_stream.py`

- [ ] **Step 1: Add missing trace test**

Add:

```python
    def test_stream_snapshot_for_missing_trace_is_not_resumable(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()

        assert sr.stream_snapshot("missing") == {
            "trace_id": "missing",
            "backlog": [],
            "listener_count": 0,
            "resumable": False,
        }
```

- [ ] **Step 2: Add restore clears snapshot test**

Add:

```python
    def test_stream_snapshot_is_not_restored_after_runtime_restore(self):
        from agentmind.routing.side_effects.session_registry import SessionRegistry

        sr = SessionRegistry()
        sr.broadcast_stream_chunk("tr-backlog", {"event": "partial", "data": "hello"})

        sr.restore_discussions({"u1": {"stop": False}})

        assert sr.stream_snapshot("tr-backlog") == {
            "trace_id": "tr-backlog",
            "backlog": [],
            "listener_count": 0,
            "resumable": False,
        }
```

- [ ] **Step 3: Run RED/GREEN check**

Run:

```bash
pytest tests/test_stream.py::TestStreamRegistry::test_stream_snapshot_for_missing_trace_is_not_resumable tests/test_stream.py::TestStreamRegistry::test_stream_snapshot_is_not_restored_after_runtime_restore -q
```

Expected: pass if Task 2 is complete. If it fails, adjust `stream_snapshot()` only.

### Task 4: RED Service Exposes Stream Snapshot Without Registering Listener

**Files:**
- Modify: `tests/test_session_runtime_service.py`

- [ ] **Step 1: Extend fake registry**

Add to `_SessionRegistry`:

```python
    def stream_snapshot(self, trace_id):
        return {
            "trace_id": trace_id,
            "backlog": [{"event": "partial", "data": "hello"}],
            "listener_count": 0,
            "resumable": True,
        }
```

- [ ] **Step 2: Add failing service test**

Add:

```python
def test_session_runtime_service_stream_snapshot_does_not_register_listener():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    session_registry = _SessionRegistry()
    result = SessionRuntimeService(
        session_registry=session_registry,
        task_service=_TaskService(),
    ).stream_snapshot("t1")

    assert result == {
        "trace_id": "t1",
        "backlog": [{"event": "partial", "data": "hello"}],
        "listener_count": 0,
        "resumable": True,
    }
    assert session_registry.registered == []
```

- [ ] **Step 3: Run RED**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_stream_snapshot_does_not_register_listener -q
```

Expected: FAIL because `SessionRuntimeService` has no `stream_snapshot()`.

### Task 5: GREEN Service Snapshot Method

**Files:**
- Modify: `src/agentmind/services/session_runtime_service.py`

- [ ] **Step 1: Add service method**

Add:

```python
    def stream_snapshot(self, trace_id: str):
        return self.session_registry.stream_snapshot(trace_id)
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_stream_snapshot_does_not_register_listener -q
```

Expected: 1 passed.

### Task 6: Regression For Live Stream Endpoint

**Files:**
- Existing tests unless a failure shows missing coverage.

- [ ] **Step 1: Run live stream service test**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_stream_events_unregisters_listener -q
```

Expected: pass. This confirms live SSE registration/unregistration still works.

- [ ] **Step 2: Run panel delegation stream test**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_task_stream_endpoint_uses_session_runtime_service -q
```

Expected: pass. This confirms the panel stream endpoint still delegates to `SessionRuntimeService.stream_events()`.

### Task 7: Documentation Update

**Files:**
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/phase3/phase-3-closure-status.md`

- [ ] **Step 1: Update panel boundary note**

Replace:

```markdown
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state and attach bindings have startup recovery support, while stream listener queues remain volatile live runtime state for a later package.
```

with:

```markdown
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state and attach bindings have startup recovery support. Stream resumability is limited to in-process backlog snapshots, and live listener queues remain volatile.
```

- [ ] **Step 2: Update next migration direction**

Replace the next direction list with:

```markdown
1. Remaining ChannelHub compatibility cleanup.
2. Decide whether persistent task-event replay belongs in a later observability package rather than Phase 4 live stream runtime.
```

- [ ] **Step 3: Update Phase 3 closure status**

In Phase 4 completed package list, add:

```markdown
10. Added an in-process stream backlog snapshot boundary behind `SessionRuntimeService`; live stream listener queues remain volatile and are not restored.
```

Replace the next-step paragraph with:

```markdown
Next, finish remaining ChannelHub compatibility cleanup. Persistent task-event replay, if needed, should be designed as an observability/task-event package instead of pretending live SSE queue objects can be recovered.
```

### Task 8: Strict Verification And Commit

**Files:**
- All modified files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_stream.py::TestStreamRegistry tests/test_session_runtime_service.py::test_session_runtime_service_stream_snapshot_does_not_register_listener tests/test_session_runtime_service.py::test_session_runtime_service_stream_events_unregisters_listener -q
```

Expected: pass.

- [ ] **Step 2: Run stream/session/panel regression**

Run:

```bash
pytest tests/test_stream.py tests/test_session_runtime_service.py tests/test_panel_api.py::TestPanelConfigServiceUsage::test_task_stream_endpoint_uses_session_runtime_service -q
```

Expected: pass.

- [ ] **Step 3: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

Expected: pass.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: pass.

- [ ] **Step 5: Run full suite**

Run:

```bash
pytest -q
```

Expected: pass.

- [ ] **Step 6: Run diff and status checks**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` has no output. `git status --short` shows only the planned files before commit.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/agentmind/routing/side_effects/session_registry.py src/agentmind/services/session_runtime_service.py tests/test_stream.py tests/test_session_runtime_service.py docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md docs/superpowers/plans/2026-05-27-phase-4-stream-resumability-boundary.md
git commit -m "refactor: add stream snapshot boundary"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: Covers stream snapshot/resumability boundary only. It explicitly excludes persistent stream-event storage, live queue restore, panel endpoint expansion, routing changes, ChannelHub changes, and Phase 5 work.
- Placeholder scan: No TODO/TBD placeholders are present.
- Type consistency: Uses existing `SessionRegistry`, `SessionRuntimeService`, `stream_events()`, `restore_discussions()`, and pytest names.
- Architecture fit: Keeps panel/API as adapters, keeps live queues in the runtime registry, and exposes replayable backlog through the service boundary without making false persistence guarantees.
