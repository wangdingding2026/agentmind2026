# AgentMind Phase 2 Memory Cards Default Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch default memory search and v4 recall to prefer `memory_cards`, with legacy `memory_entries` used only as a migration fallback for data not yet represented as cards.

**Architecture:** `MemoryService.search_memory()` becomes card-first: it queries `search_memory_cards()` and returns a compatibility-shaped dictionary containing `content`, `summary`, `card_text`, `raw_memory_id`, `source_refs`, and `_route=memory_cards`. If no card rows exist for the query, it falls back to the existing `store.search()` legacy path. `RetrievalPipeline` uses card search through `MemoryService` and adapts card dictionaries to `SearchResult` only for the existing assembler/reranker boundary; it does not add new capability to `memory_entries`.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `MemoryService`, `SqliteMemoryStore`, `SearchQuery`, `SearchResult`, and Phase 2 memory layer tables.

---

## Files

Modify:

- `tests/test_memory_cards_read_path.py`
- `tests/test_memory_retrieval_pipeline_cards.py`
- `src/agentmind/memory/service.py`
- `src/agentmind/memory/pipeline/recall.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py` except through existing delegation behavior.
- `src/agentmind/memory/sqlite_store.py` except if a card query bug blocks the default switch.
- `src/agentmind/routing/middleware/memory_retriever.py` unless tests prove it still bypasses the new default.

## Scope

In scope:

- Make `MemoryService.search_memory()` card-first.
- Preserve legacy fallback only for rows without `memory_cards`.
- Preserve public dict shape expected by callers by mapping card rows into compatibility dictionaries.
- Make v4 `RetrievalPipeline` recall use card-first service behavior.
- Add tests for card-first default, legacy fallback, and v4 recall.

Out of scope:

- Removing `memory_entries`.
- Adding new FTS/vector features to old `memory_entries`.
- Conflict detection.
- Result set navigation.
- Raw memory expansion UI/API.

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
pytest tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py -q
pytest tests/test_memory_cards_read_path.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Switch MemoryService default search to cards

- [ ] **Step 1: Update focused test to require card-first default search**

Change the existing default-search assertion in `tests/test_memory_cards_read_path.py` so `MemoryService.search_memory()` must return `_route=memory_cards` and include `card_text`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_memory_service_search_memory_cards_returns_card_shape_without_cutting_default_search -q
```

Expected: FAIL because `search_memory()` still returns legacy `store.search()` rows.

- [ ] **Step 3: Implement card-first mapping**

Modify `MemoryService.search_memory()`:

- Build `SearchQuery`.
- Call `self._store.search_memory_cards(search_query)` first.
- Map card rows to compatibility dicts with `content = card_text or summary`.
- Filter `source_agent` at the service layer.
- Return card rows if present.
- Fall back to existing `self._store.search(search_query)` only when card rows are empty.

- [ ] **Step 4: Verify GREEN**

Run the same focused test and expect PASS.

### Task 2: Preserve legacy fallback for unmigrated rows

- [ ] **Step 1: Add failing fallback test**

Add a test that inserts a legacy `memory_entries` row directly without a `memory_cards` row, then asserts `MemoryService.search_memory()` can still find it via non-card `_route`.

- [ ] **Step 2: Verify RED/GREEN**

This may pass after Task 1 if fallback is implemented; if it fails, fix only the fallback branch.

### Task 3: Switch v4 retrieval pipeline recall to card-first

- [ ] **Step 1: Add failing v4 retrieval test**

Create `tests/test_memory_retrieval_pipeline_cards.py` proving `MemoryService.retrieve(..., v4_retrieval_enabled=True)` returns recall items routed through `memory_cards` and assembled context contains the card summary.

- [ ] **Step 2: Verify RED**

Expected: FAIL because `RetrievalPipeline` still calls `store.search()` directly.

- [ ] **Step 3: Implement pipeline adapter**

Modify `RetrievalPipeline`:

- If `self._service` exists, call `self._service.search_memory(...)`.
- Convert returned dicts to `SearchResult` using `MemoryEntry.from_dict`.
- Preserve `_score` and `_route`.
- If service is absent, keep existing `store.search()` path.

- [ ] **Step 4: Verify GREEN**

Run the focused pipeline test and expect PASS.

### Task 4: Package verification

- [ ] Run focused tests.
- [ ] Run memory related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
