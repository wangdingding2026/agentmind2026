# AgentMind Phase 2 Result Set Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose result-set navigation through `MemoryService` and route memory follow-up phrases like "展开第 N 条" and "还有吗" to `memory_cards/raw_memory` result sets.

**Architecture:** `ResultSetService` remains the persistence layer for `result_sets`. `MemoryService` becomes the public memory boundary for `expand_result()`, `more_results()`, and "latest result set" lookup. `MemoryRetriever` handles follow-up intent before normal recall, using the latest result set for the user. Expansion returns raw memory content through `raw_memory`; continuation returns card rows from `memory_cards`. Legacy `memory_entries` receives no new feature surface.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `MemoryService`, `ResultSetService`, `MemoryRetriever`, `memory_cards`, `raw_memory`, and `result_sets`.

---

## Files

Modify:

- `src/agentmind/services/result_set_service.py`
- `src/agentmind/memory/service.py`
- `src/agentmind/routing/middleware/memory_retriever.py`
- `tests/test_result_set_service.py`
- `tests/test_memory_service_convergence.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `src/agentmind/routing/executors/self_reply.py`
- `src/agentmind/memory/sqlite_store.py`

## Scope

In scope:

- Add latest result-set lookup by user.
- Add `MemoryService.expand_result()` and `MemoryService.more_results()`.
- Add `MemoryRetriever` follow-up handling for:
  - `展开第 N 条`
  - `展开第 N 个`
  - `还有吗`
  - `还有别的吗`
- Return structured dictionaries that downstream code can render.

Out of scope:

- Natural language LLM parsing.
- Panel UI changes.
- Cold archive beyond `raw_memory`.
- Legacy `memory_entries` result-set support.

## Strict Testing Rules

Every production change follows RED-GREEN:

1. Add or update a focused failing test.
2. Run that exact test and confirm it fails for the expected reason.
3. Implement the smallest production change.
4. Run the exact test and confirm it passes.
5. Run package verification.
6. Only then move to the next step.

Package verification commands:

```bash
pytest tests/test_result_set_service.py tests/test_memory_service_convergence.py -q
pytest tests/test_result_set_service.py tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py tests/test_memory_service_convergence.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Expose result-set navigation through MemoryService

- [ ] Add failing tests for `MemoryService.expand_result()` and `MemoryService.more_results()` using the latest result set.
- [ ] Implement `ResultSetService.get_latest_result_set_id(user_id)`.
- [ ] Implement `MemoryService.expand_result()` and `MemoryService.more_results()`.

### Task 2: Route follow-up phrases in MemoryRetriever

- [ ] Add failing tests for `MemoryRetriever.retrieve("展开第 2 条", user_id)` and `MemoryRetriever.retrieve("还有别的吗", user_id)`.
- [ ] Implement follow-up phrase parsing before normal retrieval.
- [ ] Return raw expansion and next-page card rows as structured memory dictionaries.

### Task 3: Package verification

- [ ] Run focused tests.
- [ ] Run memory/session related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
