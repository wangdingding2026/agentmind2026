# AgentMind Phase 2 Memory Conflict Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect conflicting memory cards during write and surface conflict hints during card-first retrieval without mutating or deleting the original raw memory.

**Architecture:** Add `MemoryConflictDetector` as a card-layer component. It reads `memory_cards`, groups likely same-topic cards by normalized tag/topic signals, detects explicit opposition with conservative textual heuristics, and records conflict state in each card's `score_metadata`. `MemoryService.write_memory()` triggers detection after card dual-write. `MemoryService.search_memory()` surfaces `_conflicts` from `score_metadata` on card-first results. Legacy `memory_entries` is not extended.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `MemoryService`, `SqliteMemoryStore`, `memory_cards.score_metadata`, and `raw_memory`.

---

## Files

Create:

- `src/agentmind/memory/conflict_detector.py`
- `tests/test_memory_conflict_detector.py`

Modify:

- `src/agentmind/memory/service.py`

Do not modify in this package:

- `src/agentmind/storage/memory.py`
- `src/agentmind/memory/pipeline/write_pipeline.py`
- `src/agentmind/memory/sqlite_store.py` unless a small helper is necessary.

## Scope

In scope:

- Detect conflicts among cards for the same user and overlapping tags.
- Mark both card versions with conflict metadata.
- Preserve both raw memories.
- Surface conflict metadata in card-first search results.

Out of scope:

- AuditService persistence.
- LLM-based contradiction detection.
- Deleting, overwriting, or demoting old raw memory.
- Legacy `memory_entries` conflict behavior changes.

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
pytest tests/test_memory_conflict_detector.py -q
pytest tests/test_memory_conflict_detector.py tests/test_memory_cards_read_path.py tests/test_memory_retrieval_pipeline_cards.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py tests/test_memory_service_convergence.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Detect and mark card conflicts

- [ ] Add failing test that writes two same-topic memory cards with opposing recommendations and expects both cards' `score_metadata.conflicts` to reference each other.
- [ ] Implement `MemoryConflictDetector.detect_for_memory(memory_id)`.
- [ ] Update `MemoryService.write_memory()` to run detector after write.

### Task 2: Surface conflicts during search

- [ ] Add failing test that card-first `MemoryService.search_memory()` returns `_conflicts` for conflicted cards.
- [ ] Implement conflict metadata mapping in `_card_row_to_search_dict()`.

### Task 3: Package verification

- [ ] Run focused tests.
- [ ] Run memory/session related tests.
- [ ] Run router/panel regression.
- [ ] Run full suite.
