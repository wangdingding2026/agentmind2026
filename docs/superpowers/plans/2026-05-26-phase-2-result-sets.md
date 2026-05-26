# AgentMind Phase 2 Result Sets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add result-set persistence for card search so AgentMind can support "expand item N" and "more results" using stable `memory_cards` and `raw_memory` references.

**Architecture:** Introduce `ResultSetService` backed by the existing `result_sets` table. Result sets store ordered `memory_id` values from `memory_cards`, maintain a cursor for continuation, and expand an item by reading its `memory_card.raw_memory_id` from `raw_memory`. `MemoryService.search_memory()` creates a result set for card-first search results and attaches `_result_set_id` / `_result_index` metadata. Legacy `memory_entries` remains a fallback only and is not extended for result-set behavior.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `MemoryService`, `SqliteMemoryStore`, `raw_memory`, `memory_cards`, and `result_sets`.

---

## Files

Create:

- `src/agentmind/services/result_set_service.py`
- `tests/test_result_set_service.py`

Modify:

- `src/agentmind/memory/service.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `src/agentmind/routing/executors/self_reply.py`
- `src/agentmind/memory/sqlite_store.py`, unless a missing card/raw getter blocks the service.

## Scope

In scope:

- Create result sets from ordered card search results.
- Attach `_result_set_id` and `_result_index` to card-first `MemoryService.search_memory()` results.
- Fetch the next page for "还有吗" semantics using the persisted cursor.
- Expand the Nth result using `memory_cards.raw_memory_id -> raw_memory.content`.

Out of scope:

- Natural-language intent routing for "展开第 N 条" and "还有吗".
- Panel UI changes.
- Cold archive storage beyond `raw_memory`.
- Conflict detection.
- Any new legacy-table capability.

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
pytest tests/test_result_set_service.py -q
pytest tests/test_result_set_service.py tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: ResultSetService storage and expand

- [ ] Add failing tests for creating a result set from card ids and expanding item 2 via raw memory.
- [ ] Implement `ResultSetService.create_result_set()`.
- [ ] Implement `ResultSetService.expand_result()`.

### Task 2: Pagination cursor

- [ ] Add failing tests for `next_page()` returning deterministic pages and advancing cursor.
- [ ] Implement cursor update in `result_sets`.

### Task 3: MemoryService search metadata

- [ ] Add failing test proving card-first `MemoryService.search_memory()` attaches `_result_set_id` and 1-based `_result_index`.
- [ ] Implement result-set creation in the card-first branch only.

### Task 4: Package verification

- [ ] Run focused tests.
- [ ] Run memory/session related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
