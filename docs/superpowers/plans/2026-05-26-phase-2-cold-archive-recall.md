# AgentMind Phase 2 Cold Archive Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add controlled cold archive recall so card-first results can recover original content after raw memory has moved out of the hot `raw_memory` table.

**Architecture:** Keep normal retrieval card-first: `search_memory()` continues to search `memory_cards` and does not silently mix archive-only rows into regular recall. Add archive read methods to `SqliteMemoryStore`, expose explicit archive search through `MemoryService`, and make `ResultSetService.expand_result()` fall back from `raw_memory` to `archive.db` when a card points to archived raw content. Archive reads must be user-scoped and must not add new behavior to legacy `storage/memory.py`.

**Tech Stack:** Python 3.12, SQLite, gzip archive blobs, pytest, existing `MemoryService`, `SqliteMemoryStore`, `ResultSetService`, `memory_cards`, `raw_memory`, and `archive.db`.

---

## Files

Create:

- `tests/test_cold_archive_recall.py`

Modify:

- `src/agentmind/memory/sqlite_store.py`
- `src/agentmind/memory/service.py`
- `src/agentmind/services/result_set_service.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `tests/fixtures/memory_retrieval_cases.yaml`

## Scope

In scope:

- Read archived memory rows from `archive.db` month tables.
- Decompress `content_compressed` and return normalized memory dictionaries.
- Filter archive recall by `user_id`, `query_text`, `memory_type`, and original created date.
- Expose `MemoryService.search_archive_memory()` as an explicit cold recall API.
- Fall back to archive during result expansion when `raw_memory` no longer has the original row.
- Preserve strict user isolation for archive recall.

Out of scope:

- Moving new data into archive.
- Rewriting the archival worker.
- Adding archive rows to default `search_memory()` results.
- Changing panel UI.
- LLM scoring or semantic archive search.

## Strict Testing Rules

Every change follows RED-GREEN:

1. Add one focused failing test.
2. Run that exact test and confirm it fails for the expected missing method or missing fallback.
3. Implement the smallest code to pass.
4. Run the exact test and confirm it passes.
5. Repeat for the next behavior.

Package verification commands:

```bash
pytest tests/test_cold_archive_recall.py -q
pytest tests/test_cold_archive_recall.py tests/test_result_set_service.py tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_retrieval_eval.py tests/test_memory_layers.py tests/test_memory.py tests/test_session_service.py tests/test_memory_service_convergence.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: Explicit archive search

- [ ] Add a failing test that seeds `archive.db` and calls `MemoryService.search_archive_memory()`.
- [ ] Confirm it fails because `MemoryService.search_archive_memory()` does not exist.
- [ ] Implement `SqliteMemoryStore.search_archive_memory()` and `MemoryService.search_archive_memory()`.
- [ ] Confirm the test passes.

### Task 2: Archive user isolation

- [ ] Add a failing test proving archive search does not return another user's archived row.
- [ ] Confirm it fails before the archive filter is complete.
- [ ] Add strict `user_id` filtering in archive search.
- [ ] Confirm the test passes.

### Task 3: Result expansion archive fallback

- [ ] Add a failing test with a hot card, missing `raw_memory`, and archived original content.
- [ ] Confirm `ResultSetService.expand_result()` currently returns empty content.
- [ ] Make expansion fall back to `SqliteMemoryStore.get_archived_memory()`.
- [ ] Mark expanded rows with `_raw_route="archive"` while preserving `_route="result_set_expand"` at the `MemoryService` boundary.
- [ ] Confirm the test passes.

### Task 4: Package verification

- [ ] Run focused archive tests.
- [ ] Run related memory/session/result-set tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
- [ ] Confirm deleted `记忆和检索模块优化方案.md` is still absent.
