# AgentMind Phase 0 Architecture Dependency Inventory

Date: 2026-05-26

## Purpose

This inventory records direct dependencies on configuration files, task storage,
memory storage, process state, and broad exception handling before Phase 1
service-layer work. It is intended to guide migration order, not to prescribe a
large rewrite.

## Summary Counts

Commands were run against `src/agentmind`.

| Dependency type | Approximate references |
|---|---:|
| YAML/config file access | 111 |
| Task record/query functions | 65 |
| Memory legacy entry points / direct connection access | 67 |
| `app.state` access | 43 |
| Broad `except Exception` handling | 162 |
| Python source files | 85 |

## Configuration Access Hotspots

Direct YAML/config access is concentrated in:

- `src/agentmind/main.py`
  - Loads `settings.yaml`.
  - Constructs `AgentRegistry` from `agents.yaml`.
  - Constructs `RuleEngine` from `routes.yaml`.
  - Owns local auth token creation.
- `src/agentmind/panel/server.py`
  - Reads and writes `agents.yaml`, `routes.yaml`, and `settings.yaml`.
  - Persists Feishu, route, settings, and agent tag/toggle changes directly.
- `src/agentmind/agents/registry.py`
  - Reads `agents.yaml` directly.
- `src/agentmind/agents/discovery.py`
  - Reads and writes discovered agent config.
- `src/agentmind/core/rule_engine.py`
  - Reads route rules directly.
- `src/agentmind/api/orchestration.py`
  - Reads and writes `orchestrations.yaml`.
- `src/agentmind/storage/db.py`
  - Reads history settings from `settings.yaml`.
- `src/agentmind/storage/memory.py`
  - Reads memory and embedding settings.
  - Reads agent credibility from `agents.yaml`.
- `src/agentmind/routing/middleware/memory_retriever.py`
  - Reads memory settings.
- `src/agentmind/routing/side_effects/memory_writer.py`
  - Reads memory settings.
- `src/agentmind/core/core_llm.py`
  - Reads core LLM settings.

## Task Storage Hotspots

Task lifecycle functions currently live in `src/agentmind/storage/db.py` and are
called directly from multiple business modules.

Primary direct callers:

- `src/agentmind/api/router.py`
  - Starts, updates, and ends tasks.
  - Records attached turns.
  - Reads task detail for Attach.
- `src/agentmind/routing/executors/base.py`
  - Ends tasks after execution/fallback.
- `src/agentmind/routing/executors/single_agent.py`
  - Updates executing status and ends tasks.
- `src/agentmind/routing/executors/self_reply.py`
  - Updates executing status for AgentMind self replies.
- `src/agentmind/panel/server.py`
  - Queries task lists, task stats, task details, recent errors, and metrics.
- `src/agentmind/main.py`
  - Marks timed-out tasks retriable during startup.

Phase 1 migration target:

- Add `TaskService` as a thin wrapper first.
- Keep old `record_task_*` functions compatible.
- Move direct panel and routing calls gradually after compatibility is stable.

## Memory Storage Hotspots

The project currently has both legacy memory functions and the v4
`MemoryService`.

Key files:

- `src/agentmind/storage/memory.py`
  - Legacy write/search/stats/cleanup API.
  - Owns `_get_memory_conn`.
  - Contains old embedding, conflict, and search logic.
- `src/agentmind/memory/service.py`
  - v4 service entry point for write/search/stats/cleanup/session/retrieve.
  - Still contains process-local session state.
- `src/agentmind/memory/sqlite_store.py`
  - v4 store implementation.
- `src/agentmind/routing/middleware/memory_retriever.py`
  - Uses both `MemoryService().retrieve` and legacy `search_memory`.
- `src/agentmind/routing/side_effects/memory_writer.py`
  - Uses both `MemoryService` and legacy `write_memory`.
- `src/agentmind/routing/side_effects/trace_recorder.py`
  - Writes trace through memory-compatible paths and reads trace from memory DB.
- `src/agentmind/api/orchestration.py`
  - Writes orchestration results to memory.
- `src/agentmind/panel/server.py`
  - Searches, stats, cleanup, and direct delete through `_get_memory_conn`.

Phase 2 migration target:

- Make `MemoryService` the only business-facing memory entry point.
- Demote `storage/memory.py` to compatibility.
- Move trace out of user memory paths.

## Process State Hotspots

`app.state` is used as the runtime service container, but with direct access
from route handlers and panel handlers.

Primary state fields:

- `agent_registry`
- `rule_engine`
- `settings`
- `auth_token`
- `feishu_adapter`
- `memory_scheduler`
- `attach_registry`
- `routing_pipeline`
- `agents_config_path`

Primary files:

- `src/agentmind/main.py`
- `src/agentmind/api/router.py`
- `src/agentmind/api/agents.py`
- `src/agentmind/api/orchestration.py`
- `src/agentmind/panel/server.py`

Phase 1 and Phase 4 migration target:

- Introduce services first.
- Keep `app.state` as wiring until `startup/app_factory.py` exists.
- Avoid making panel endpoints call storage/config files directly.

## Broad Exception Handling

There are many broad exception handlers. Some are acceptable best-effort
degradation, but many hide operational failures.

Important areas:

- Startup background tasks in `main.py`.
- Memory write/search/embedding paths in `storage/memory.py` and
  `memory/sqlite_store.py`.
- Feishu channel callbacks in `channels/feishu.py`.
- Routing memory and trace side effects.

Migration rule:

- Do not try to fix all broad exception handling in Phase 1.
- When touching a path, preserve user-facing best-effort behavior but add
  logging or route errors through future `AuditService`/`TraceService` seams.

## Recommended Phase 1 Order

1. `ConfigService` thin wrapper.
2. `TaskService` thin wrapper.
3. Migrate panel settings/routes/Feishu config writes to `ConfigService`.
4. Change old task functions to delegate to `TaskService` without changing
   callers.
5. Only then begin `main.py` and `RoutingService` extraction.

## Phase 1 Package 1 Status

Completed:

- `ConfigService` added and used for config reads, writes, and masking.
- `TaskService` added and used as the compatibility layer behind
  `storage.db` task lifecycle functions.
- Panel settings, Feishu config, route rules, and embedding status now use
  `ConfigService`.

Still deferred to later Phase 1 packages:

- `main.py` startup slimming.
- `RoutingService` extraction from `api/router.py`.
- Agent registry management service extraction.
- Any memory-service or trace-service split.
