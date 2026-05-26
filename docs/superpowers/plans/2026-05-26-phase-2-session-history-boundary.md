# AgentMind Phase 2 Session Context and History Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the retrieval boundary explicit: current session context comes from Working Memory, while historical recall searches `memory_cards` and excludes the active conversation by default.

**Architecture:** Add a small active-conversation lookup to `SessionService`/`MemoryService`. Extend `SearchQuery` and card search with an `exclude_conversation_id` filter. `RetrievalPipeline` uses the active conversation id when doing historical recall, so cards from the current active conversation are not duplicated into the historical recall section. Legacy `memory_entries` remains only a migration fallback and receives the same exclusion parameter when used.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `SessionService`, `MemoryService`, `SqliteMemoryStore`, `RetrievalPipeline`, `SearchQuery`, and memory card tables.

---

## Files

Modify:

- `src/agentmind/memory/types.py`
- `src/agentmind/memory/sqlite_store.py`
- `src/agentmind/memory/service.py`
- `src/agentmind/memory/pipeline/recall.py`
- `src/agentmind/services/session_service.py`
- `tests/test_session_service.py`
- `tests/test_memory_retrieval_pipeline_cards.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `src/agentmind/routing/executors/self_reply.py`
- `src/agentmind/routing/middleware/memory_retriever.py`

## Scope

In scope:

- Add `SessionService.get_active_conversation_id(user_id)`.
- Expose `MemoryService.get_active_conversation_id(user_id)`.
- Add `SearchQuery.exclude_conversation_id`.
- Make `SqliteMemoryStore.search_memory_cards()` exclude the active conversation when requested.
- Make legacy fallback respect the same exclusion only as migration compatibility.
- Make v4 retrieval pass the active conversation exclusion during historical recall.
- Verify Working Memory still injects current session context after historical exclusion.

Out of scope:

- Replacing `conv-*` with `sess-*`.
- Changing `/new` command behavior beyond existing session close/clear semantics.
- Result set navigation.
- Conflict detection.
- Any new feature on legacy `memory_entries` beyond honoring the shared exclusion field.

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
pytest tests/test_session_service.py tests/test_memory_retrieval_pipeline_cards.py -q
pytest tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Active conversation lookup

- [ ] Add a failing `SessionService.get_active_conversation_id()` test.
- [ ] Implement the lookup from `conversations` where `status='active'`.
- [ ] Expose the same method on `MemoryService`.

### Task 2: Historical recall excludes active conversation

- [ ] Add a failing v4 retrieval test with one active-conversation card, one historical card, and current Working Memory.
- [ ] Implement `SearchQuery.exclude_conversation_id`.
- [ ] Make card search and fallback search honor the exclusion.
- [ ] Make `RetrievalPipeline` pass the active conversation id to `MemoryService.search_memory()`.

### Task 3: Package verification

- [ ] Run focused tests.
- [ ] Run memory/session related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
