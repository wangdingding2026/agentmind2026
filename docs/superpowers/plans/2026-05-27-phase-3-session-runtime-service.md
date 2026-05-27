# Phase 3 Session Runtime Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel session, attach, and stream runtime access behind a service-layer boundary.

**Architecture:** `SessionRuntimeService` owns panel-facing runtime operations for active sessions, task attach binding, and task stream listener lifecycle. The existing in-process `session_registry` and `attach_registry` remain infrastructure/runtime dependencies for this package; this is a service boundary migration, not a persistence migration. Feishu connect/disconnect/status remain Phase 4 `ChannelHub` transition boundaries.

**Tech Stack:** FastAPI panel router, SSE response adapter, service-layer Python class, pytest, existing `TaskService` and `session_registry`.

---

## Scope

Target in this package:

- Add `src/agentmind/services/session_runtime_service.py`.
- Add `tests/test_session_runtime_service.py`.
- Move these panel operations into service methods:
  - active sessions view;
  - attach binding;
  - stream listener registration/unregistration and event generator.
- Update panel boundary audit so `active_sessions`, `attach_to_task`, and `panel_task_stream` become service-backed.

Transition boundaries preserved:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`

Out of scope:

- Do not persist sessions/streams in SQLite in this package.
- Do not change `SessionRegistry` behavior.
- Do not change `AttachRegistry` behavior.
- Do not create `ChannelHub`.
- Do not migrate Feishu lifecycle.

## Files

- Create: `src/agentmind/services/session_runtime_service.py`
  - Provides `active_sessions()`, `attach_to_task()`, and `stream_events()`.
- Create: `tests/test_session_runtime_service.py`
  - Tests runtime view mapping, attach errors/success, and stream cleanup.
- Modify: `src/agentmind/panel/server.py`
  - Delegates session/attach/stream handlers to `SessionRuntimeService`.
  - Keeps `EventSourceResponse` as HTTP adapter in panel.
- Modify: `tests/test_panel_api.py`
  - Adds delegation tests for the three panel endpoints.
- Modify: `tests/test_panel_control_plane_boundary.py`
  - Moves the three handlers from transition to service-backed.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Updates target/transition lists and next migration direction.

## Tasks

### Task 1: RED Service Tests

- [ ] **Step 1: Write failing service tests**

Add tests for:

- `active_sessions()` maps discussion registry state and calls `TaskService.query_tasks(limit=5, status="executing")`.
- `attach_to_task()` returns missing-session error when no session id is provided.
- `attach_to_task()` returns disabled error when no attach registry exists.
- `attach_to_task()` binds session id to trace id and returns the existing response shape.
- `stream_events()` registers a listener, yields chunks, and unregisters the listener in `finally`.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_session_runtime_service.py -q
```

Expected: FAIL because `SessionRuntimeService` does not exist.

### Task 2: GREEN Service

- [ ] **Step 1: Implement `SessionRuntimeService`**

Use dependency injection:

- `session_registry`
- `task_service`
- optional `attach_registry`

Default `session_registry` imports `agentmind.routing.side_effects.session_registry.session_registry`.
Default `task_service` is `TaskService()`.

- [ ] **Step 2: Run service GREEN**

```bash
pytest tests/test_session_runtime_service.py -q
```

Expected: PASS.

### Task 3: RED Panel Delegation

- [ ] **Step 1: Add panel delegation tests**

Monkeypatch `agentmind.panel.server.SessionRuntimeService`, then call:

- `GET /panel/api/sessions`
- `POST /panel/api/tasks/{trace_id}/attach?session_id=s1`
- `GET /panel/api/tasks/{trace_id}/stream`

Assert panel returns/delegates service results. For the stream endpoint, assert the response is an SSE response built from the service generator.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_sessions_endpoint_uses_session_runtime_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_attach_endpoint_uses_session_runtime_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_task_stream_endpoint_uses_session_runtime_service -q
```

Expected: FAIL because panel still touches runtime state directly.

### Task 4: GREEN Panel Migration

- [ ] **Step 1: Migrate panel handlers**

Add `_session_runtime_service(request=None)` helper and delegate:

- `active_sessions`
- `attach_to_task`
- `panel_task_stream`

- [ ] **Step 2: Update boundary audit**

Move the three handlers from transition to service-backed. Only Feishu lifecycle/status should remain transition in this audit document.

- [ ] **Step 3: Run focused GREEN**

```bash
pytest tests/test_session_runtime_service.py tests/test_panel_api.py::TestPanelConfigServiceUsage::test_sessions_endpoint_uses_session_runtime_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_attach_endpoint_uses_session_runtime_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_task_stream_endpoint_uses_session_runtime_service tests/test_panel_control_plane_boundary.py -q
```

Expected: PASS.

### Task 5: Verification

- [ ] **Step 1: Run panel regression**

```bash
pytest tests/test_panel_api.py -q
```

- [ ] **Step 2: Run session/attach/stream regression**

```bash
pytest tests/test_session_runtime_service.py tests/test_stream.py tests/test_attach.py -q
```

- [ ] **Step 3: Run architecture regression**

```bash
pytest tests/test_phase2_architecture_audit.py tests/test_panel_control_plane_boundary.py -q
```

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 5: Run full regression**

```bash
pytest -q
```

### Task 6: Commit

- [ ] **Step 1: Check diff hygiene**

```bash
git diff --check
git status --short
```

- [ ] **Step 2: Review and commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-session-runtime-service.md docs/phase3/panel-control-plane-boundary.md src/agentmind/services/session_runtime_service.py src/agentmind/panel/server.py tests/test_session_runtime_service.py tests/test_panel_api.py tests/test_panel_control_plane_boundary.py
git commit -m "refactor: route session runtime through service"
```

## Self-Review

- Spec coverage: Covers panel runtime boundary migration only.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: Panel remains an adapter; service owns runtime operations; underlying in-process registries remain temporary infrastructure pending a persistence/runtime-state package.
