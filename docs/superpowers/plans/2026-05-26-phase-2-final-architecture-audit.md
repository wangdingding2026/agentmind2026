# AgentMind Phase 2 Final Architecture Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock Phase 2 memory architecture boundaries so business code uses `MemoryService`, `TraceService`, `SessionService`, and result/archive services instead of legacy memory storage internals.

**Architecture:** Add architecture invariant tests that scan `src/agentmind` for forbidden legacy memory access outside approved low-level modules. Then migrate remaining business-layer callers from `agentmind.storage.memory` and direct `memory_entries` deletes to `MemoryService`/store methods. Keep legacy compatibility code only inside `storage/memory.py`, migrations, workers, and the explicit trace fallback.

**Tech Stack:** Python 3.12, pytest, pathlib source scanning, existing `MemoryService`, `TraceService`, `SqliteMemoryStore`, FastAPI panel/router tests.

---

## Files

Create:

- `tests/test_phase2_architecture_audit.py`

Modify:

- `src/agentmind/startup.py`
- `src/agentmind/api/router.py`
- `src/agentmind/api/orchestration.py`
- `src/agentmind/services/routing_service.py`
- `src/agentmind/panel/server.py`
- `src/agentmind/memory/sqlite_store.py`
- `tests/test_panel_api.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py` except if an existing compatibility test requires no-op import compatibility.
- `记忆和检索模块优化方案.md`

## Scope

In scope:

- Prevent business modules from importing `agentmind.storage.memory`.
- Prevent business modules from direct `_get_memory_conn` and `memory_entries` mutation.
- Move panel memory search/stats/cleanup/delete to `MemoryService`.
- Move route/discussion/orchestration writes to `MemoryService`.
- Move startup periodic cleanup to `MemoryService`.
- Add a store-level `delete_memory()` path that deletes legacy row, FTS/vector rows, `raw_memory`, `memory_cards`, and result-set references as needed for panel delete.

Out of scope:

- Removing legacy `storage/memory.py`.
- Rewriting memory workers, migrations, or low-level store internals.
- Removing TraceService legacy trace fallback.
- Changing UI behavior.

## Allowed Legacy Memory Zones

The architecture test may allow legacy memory internals only in:

- `src/agentmind/storage/memory.py`
- `src/agentmind/storage/db.py`
- `src/agentmind/memory/sqlite_store.py`
- `src/agentmind/memory/migrations/`
- `src/agentmind/memory/workers/`
- `src/agentmind/memory/pipeline/write_pipeline.py`
- `src/agentmind/memory/components/`
- `src/agentmind/services/trace_service.py` only for `_get_legacy_memory_trace_sync`

Business modules must not import `agentmind.storage.memory`.

## Strict Testing Rules

Every change follows RED-GREEN:

1. Add a focused architecture test.
2. Run that exact test and confirm it fails on the current violation.
3. Migrate the smallest production code needed.
4. Run the exact test and confirm it passes.
5. Repeat for behavior tests when a route changes.

Package verification commands:

```bash
pytest tests/test_phase2_architecture_audit.py -q
pytest tests/test_panel_api.py::test_panel_memory_delete_uses_memory_service -q
pytest tests/test_phase2_architecture_audit.py tests/test_cold_archive_recall.py tests/test_result_set_service.py tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_retrieval_eval.py tests/test_memory_layers.py tests/test_memory.py tests/test_session_service.py tests/test_memory_service_convergence.py tests/test_trace_service.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: Lock business-layer imports

- [ ] Add `tests/test_phase2_architecture_audit.py` scanning business files for `agentmind.storage.memory` imports and direct `_get_memory_conn`.
- [ ] Confirm RED fails on current imports in startup/router/orchestration/routing service/panel/memory writer.
- [ ] Migrate those business modules to `MemoryService`.
- [ ] Confirm architecture test passes.

### Task 2: Panel memory delete service boundary

- [ ] Add a failing panel test proving `/memory/{memory_id}` delegates to `MemoryService.delete_memory()`.
- [ ] Implement `MemoryService.delete_memory()` and store deletion of `memory_entries`, `memory_fts`, vector rows, `raw_memory`, and `memory_cards`.
- [ ] Update panel delete route to call `MemoryService`.
- [ ] Confirm focused panel test passes.

### Task 3: Final Phase 2 related verification

- [ ] Run Phase 2 architecture audit tests.
- [ ] Run memory/session/result/archive/trace related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
- [ ] Confirm deleted `记忆和检索模块优化方案.md` is still absent.
