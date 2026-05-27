# AgentMind Phase 3 Orchestration Execution Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move orchestration plan management, trigger matching, and execution event generation into the new orchestration service/engine boundary.

**Architecture:** `OrchestrationService` owns persisted orchestration plans through `ConfigService`, trigger matching, and usage updates. `OrchestrationEngine` owns DAG execution event generation. Legacy API and router modules remain only as compatibility adapters that delegate to the new service/engine; they must not keep independent orchestration core logic.

**Tech Stack:** Python 3.12, dataclasses, async generators, FastAPI SSE compatibility, pytest, pytest-asyncio.

---

## Architecture Constraints

Target architecture:

- `agentmind.services.orchestration_service.OrchestrationService`
  - Reads/writes orchestration plans through `ConfigService`.
  - Saves, lists, deletes, matches trigger words, and increments usage.
- `agentmind.orchestration.engine.OrchestrationEngine`
  - Validates DAGs.
  - Sorts DAG steps.
  - Builds dependency context.
  - Executes plans as normalized orchestration events.
- `agentmind.api.orchestration`
  - Compatibility HTTP layer only.
  - May translate engine events to SSE responses.
  - Must not directly read/write orchestration YAML after this package.
- `agentmind.services.routing_service`
  - May expose old helper function names temporarily.
  - Must call `OrchestrationService`/`OrchestrationEngine`, not API private functions.

Transition compatibility:

- Keep `_load_orchestrations`, `_save_orchestrations`, and `_increment_orchestration_usage` in `api/orchestration.py` for old tests/imports, but make them wrappers over `OrchestrationService`.
- Keep `routing_service._match_orchestration` and `_execute_orchestration_plan` as temporary adapters over `OrchestrationService`/`OrchestrationEngine`.
- Keep `api.router._match_orchestration` and `_execute_orchestration_plan` as temporary adapters or delegate to `routing_service` if still imported by tests.

Not allowed:

- Adding new long-term dependencies from services to API modules.
- Creating a second orchestration execution algorithm in routing code.
- Protecting old behavior if it conflicts with the new single execution path.
- Restoring deleted file `记忆和检索模块优化方案.md`.

Out of scope:

- Parallel DAG execution.
- Retry/skip/stop policy.
- Full trace schema.
- AuditService.
- Phase 4 ChannelHub.

## Files

Create:

- `src/agentmind/services/orchestration_service.py`
- `tests/test_orchestration_service.py`

Modify:

- `src/agentmind/orchestration/engine.py`
- `src/agentmind/api/orchestration.py`
- `src/agentmind/services/routing_service.py`
- `src/agentmind/api/router.py`
- `src/agentmind/services/__init__.py`
- `tests/test_orchestration_engine.py`

Do not modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/connectors/*`
- `src/agentmind/services/protocol_gateway.py`
- Deleted file `记忆和检索模块优化方案.md`

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_orchestration_service.py -q
pytest tests/test_orchestration_engine.py -q
pytest tests/test_orchestration.py -q
pytest tests/test_orchestration.py tests/test_router.py tests/test_e2e_scenarios.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: OrchestrationService Owns Plans And Trigger Matching

**Files:**

- Create: `tests/test_orchestration_service.py`
- Create: `src/agentmind/services/orchestration_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [x] **Step 1: Write RED tests**

Create `tests/test_orchestration_service.py` with tests for:

- Saving a plan preserves existing `usage_count`.
- Listing plans returns persisted plans.
- Deleting removes a plan.
- Matching trigger words is case-insensitive and increments usage.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_orchestration_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.orchestration_service'`.

- [x] **Step 3: Implement minimal service**

Add `OrchestrationService` with:

- `list_plans() -> list[dict]`
- `save_plan(plan_id: str, name: str, trigger_words: list[str], steps: list[dict]) -> dict`
- `delete_plan(plan_id: str) -> dict`
- `increment_usage(plan_id: str) -> None`
- `match_plan(message: str) -> dict | None`

Use `ConfigService.read_orchestrations()` and `ConfigService.write_orchestrations()`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_orchestration_service.py -q
```

Expected: PASS.

---

### Task 2: OrchestrationEngine Owns Execution Events

**Files:**

- Modify: `src/agentmind/orchestration/engine.py`
- Modify: `tests/test_orchestration_engine.py`

- [x] **Step 1: Write RED tests**

Append tests that instantiate fake executors and assert:

- `execute_events()` emits `node_status executing`, `partial`, `node_status completed`, and final `status`.
- Dependency output is injected into downstream step instructions.
- Missing executor emits `node_status failed`.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_orchestration_engine.py::test_engine_execute_events_streams_ordered_step_events -q
```

Expected: FAIL with `AttributeError: 'OrchestrationEngine' object has no attribute 'execute_events'`.

- [x] **Step 3: Implement event execution**

Add `execute_events(plan, agent_registry, memory_writer=None)`.

Normalized event shape:

```python
{"event": "node_status", "data": {"step_id": 1, "status": "executing"}}
{"event": "partial", "data": {"step_id": 1, "content": "..."}}
{"event": "node_status", "data": {"step_id": 1, "status": "completed"}}
{"event": "status", "data": {"status": "orchestration_complete", "plan_id": plan.plan_id}}
```

Use `execute_stream()` as the execution primitive so API SSE and routing text mode share the same path.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_orchestration_engine.py -q
```

Expected: PASS.

---

### Task 3: Legacy API Delegates Plan Management And Execution

**Files:**

- Modify: `src/agentmind/api/orchestration.py`
- Modify: `tests/test_orchestration_service.py`

- [x] **Step 1: Write RED compatibility tests**

Add tests that monkeypatch `agentmind.api.orchestration._orchestration_service` and assert:

- `_load_orchestrations()` calls `list_plans()`.
- `_save_orchestrations(plans)` writes through the service boundary.
- `_increment_orchestration_usage(plan_id)` calls `increment_usage(plan_id)`.

Add an API endpoint test if needed to verify `/orchestration/execute` returns events produced by `_DEFAULT_ENGINE.execute_events()`.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_orchestration_service.py::test_api_orchestration_legacy_storage_helpers_delegate_to_service -q
```

Expected: FAIL because API helpers still own storage.

- [x] **Step 3: Replace API storage and execution logic with adapters**

In `api/orchestration.py`:

- Create `_orchestration_service()` returning `OrchestrationService(CONFIG_DIR)`.
- Convert storage helpers to service wrappers.
- Convert `execute_dag_plan()` to call `_DEFAULT_ENGINE.execute_events()`.
- Keep `_write_step_memory()` as the temporary API-local memory writer.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_orchestration_service.py tests/test_orchestration.py -q
```

Expected: PASS.

---

### Task 4: Router Compatibility Delegates To Service/Engine

**Files:**

- Modify: `src/agentmind/services/routing_service.py`
- Modify: `src/agentmind/api/router.py`
- Modify: `tests/test_orchestration_service.py`

- [x] **Step 1: Write RED tests**

Add tests that monkeypatch service/engine constructors and assert:

- `routing_service._match_orchestration()` calls `OrchestrationService.match_plan()`.
- `routing_service._execute_orchestration_plan()` uses `OrchestrationEngine.execute_events()`.
- `api.router._match_orchestration()` no longer imports API storage helpers and delegates to `routing_service` or `OrchestrationService`.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_orchestration_service.py::test_routing_service_match_orchestration_delegates_to_orchestration_service -q
```

Expected: FAIL because routing still imports API storage helpers.

- [x] **Step 3: Implement adapters**

In `services/routing_service.py`:

- `_match_orchestration()` calls `OrchestrationService().match_plan(msg)`.
- `_execute_orchestration_plan()` builds `OrchestrationPlan`, iterates `OrchestrationEngine().execute_events()`, and sends text chunks only from `partial`/failed events.

In `api/router.py`:

- Make `_match_orchestration()` and `_execute_orchestration_plan()` delegate to `services.routing_service`.
- Do not copy execution logic.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_orchestration_service.py -q
pytest tests/test_orchestration.py tests/test_router.py tests/test_e2e_scenarios.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_orchestration_service.py -q
pytest tests/test_orchestration_engine.py -q
pytest tests/test_orchestration.py -q
pytest tests/test_orchestration.py tests/test_router.py tests/test_e2e_scenarios.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-orchestration-execution.md tests/test_orchestration_service.py tests/test_orchestration_engine.py src/agentmind/services/orchestration_service.py src/agentmind/services/__init__.py src/agentmind/orchestration/engine.py src/agentmind/api/orchestration.py src/agentmind/services/routing_service.py src/agentmind/api/router.py
git commit -m "refactor: centralize orchestration execution"
```
