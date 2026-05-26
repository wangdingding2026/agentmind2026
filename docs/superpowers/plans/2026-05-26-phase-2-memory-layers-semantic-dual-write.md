# AgentMind Phase 2 Memory Layers Semantic Dual-Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `memory_cards` dual-write records with semantic retrieval-ready fields while keeping current recall/search behavior unchanged.

**Architecture:** Extend `memory_cards` idempotently with `card_text`, `source_refs`, `score_metadata`, and `session_id`. Populate these fields from `MemoryEntry` at write time. Keep `memory_entries` as the active search source; this package only prepares card data for the later recall switch.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `SqliteMemoryStore`, `MemoryService`, and memory layer schema.

---

## Current Baseline

Phase 2 memory layers schema package is green:

```bash
pytest tests/test_memory_layers.py -q
pytest tests/test_memory_layers.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py tests/test_trace_service.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

Expected baseline:

```text
3 passed
88 passed
48 passed
360 passed, 4 warnings
```

## Files

Create:

- `tests/test_memory_layers_semantic.py`

Modify:

- `src/agentmind/memory/migrations/runner.py`
- `src/agentmind/memory/sqlite_store.py`

Do not modify in this package:

- `src/agentmind/memory/pipeline/recall.py`
- `src/agentmind/memory/pipeline/assembler.py`
- `src/agentmind/routing/middleware/memory_retriever.py`
- `src/agentmind/memory/service.py`

## Scope

In scope:

- Add idempotent `memory_cards` columns:
  - `card_text`
  - `source_refs`
  - `score_metadata`
  - `session_id`
- Backfill the columns for existing rows with safe defaults.
- Populate enhanced card fields on single insert and batch insert.
- Preserve current search behavior through `memory_entries`.

Out of scope:

- Switching recall/search to `memory_cards`.
- Adding FTS or vector indexes to card text.
- Result set pagination behavior.
- Conflict detection.
- AuditService.

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
pytest tests/test_memory_layers_semantic.py -q
pytest tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Add semantic card columns

**Files:**

- Create: `tests/test_memory_layers_semantic.py`
- Modify: `src/agentmind/memory/migrations/runner.py`

- [ ] **Step 1: Write failing migration test**

Create `tests/test_memory_layers_semantic.py`:

```python
import sqlite3


def test_memory_cards_semantic_columns_exist_after_initialize():
    from agentmind.storage.db import DATA_DIR, initialize_memory_db

    initialize_memory_db()

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(memory_cards)").fetchall()
        }
    finally:
        conn.close()

    assert {"card_text", "source_refs", "score_metadata", "session_id"} <= cols
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_layers_semantic.py::test_memory_cards_semantic_columns_exist_after_initialize -q
```

Expected: FAIL because those `memory_cards` columns do not exist.

- [ ] **Step 3: Implement idempotent card-column migration**

Modify `ensure_memory_layer_tables()` in `src/agentmind/memory/migrations/runner.py`:

- Add the columns to the `CREATE TABLE IF NOT EXISTS memory_cards` definition.
- Add `_add_columns(conn, "memory_cards", [...])` after table creation so existing DBs get the columns.
- Add indexes:
  - `idx_memory_cards_session`
  - `idx_memory_cards_type_importance`

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_layers_semantic.py::test_memory_cards_semantic_columns_exist_after_initialize -q
```

Expected: PASS.

---

### Task 2: Populate semantic card fields on write

**Files:**

- Modify: `tests/test_memory_layers_semantic.py`
- Modify: `src/agentmind/memory/sqlite_store.py`

- [ ] **Step 1: Add failing semantic dual-write test**

Append to `tests/test_memory_layers_semantic.py`:

```python
import json

import pytest

from agentmind.memory.types import MemoryEntry, MemoryType


@pytest.mark.asyncio
async def test_memory_card_semantic_fields_populated_on_insert():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
    entry = MemoryEntry(
        memory_id="semantic-card-1",
        content="Full raw source about retrieval cards",
        summary="Retrieval cards summarize raw memory",
        source_agent="agent-a",
        source_task_id="task-1",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        conversation_id="conv-1",
        importance=0.82,
        content_hash="hash-1",
        parent_id="parent-1",
        tags=["retrieval", "card"],
    )

    await store.insert(entry)

    card = await store.get_memory_card("semantic-card-1")

    assert card["card_text"] == "Retrieval cards summarize raw memory\n\nFull raw source about retrieval cards"
    assert card["session_id"] == "conv-1"
    assert card["source_refs"] == {
        "raw_memory_id": "semantic-card-1",
        "source_agent": "agent-a",
        "source_task_id": "task-1",
        "parent_id": "parent-1",
    }
    assert card["score_metadata"] == {
        "importance": 0.82,
        "memory_type": "semantic",
        "content_hash": "hash-1",
        "access_level": "shared",
    }
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_layers_semantic.py::test_memory_card_semantic_fields_populated_on_insert -q
```

Expected: FAIL because card helper does not return these fields and insert does not populate them.

- [ ] **Step 3: Implement semantic dual-write fields**

Modify `_upsert_memory_layers()`:

- Build `card_text` as `summary + "\n\n" + content` when summary exists, otherwise content.
- Build `source_refs` JSON from raw id, source agent, task id, parent id.
- Build `score_metadata` JSON from importance, memory type, content hash, access level.
- Store `session_id` from `entry.conversation_id`.

Modify `_get_memory_card_sync()`:

- Parse `tags` as list.
- Parse `source_refs` and `score_metadata` as dicts.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_layers_semantic.py::test_memory_card_semantic_fields_populated_on_insert -q
```

Expected: PASS.

---

### Task 3: Preserve current search compatibility

**Files:**

- Modify: `tests/test_memory_layers_semantic.py`

- [ ] **Step 1: Add compatibility test**

Append to `tests/test_memory_layers_semantic.py`:

```python
@pytest.mark.asyncio
async def test_semantic_card_enrichment_does_not_change_search_path():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "semantic-search-compat-1",
        "content": "search should still use compatibility memory entries",
        "summary": "compat card search",
        "source_agent": "agent-a",
        "source_task_id": "task-1",
        "user_id": "u1",
        "tags": ["compat"],
    })

    rows = await svc.search_memory(query="compatibility memory entries", user_id="u1", limit=5)
    card = await svc.store.get_memory_card("semantic-search-compat-1")

    assert any(r["memory_id"] == "semantic-search-compat-1" for r in rows)
    assert "compat card search" in card["card_text"]
```

- [ ] **Step 2: Verify GREEN**

Run:

```bash
pytest tests/test_memory_layers_semantic.py::test_semantic_card_enrichment_does_not_change_search_path -q
```

Expected: PASS after Task 2. If it fails, fix only the compatibility issue exposed by this test.

---

### Task 4: Package verification

**Files:**

- Modify only the files listed above

- [ ] **Step 1: Run focused and related verification**

Run:

```bash
pytest tests/test_memory_layers_semantic.py -q
pytest tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full verification**

Run:

```bash
pytest -q
```

Expected:

```text
full suite remains green
```

## Self-Review

- Spec coverage: Covers semantic dual-write enhancement only: card fields, idempotent schema, and compatibility search.
- Intentional gaps: recall does not use `memory_cards`, no card FTS/vector indexes, no result-set behavior, no conflict/audit.
- Placeholder scan: No placeholders remain.
- Type consistency: `source_refs` and `score_metadata` are JSON in SQLite and dicts in helper return values.
