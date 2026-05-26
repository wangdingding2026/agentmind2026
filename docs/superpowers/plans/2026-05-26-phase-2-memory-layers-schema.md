# AgentMind Phase 2 Memory Layers Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the first memory-layer foundation by adding `raw_memory`, `memory_cards`, `sessions`, and `result_sets` schema plus dual-write support, without changing current recall ranking or context assembly.

**Architecture:** Keep `memory_entries` as the compatibility source for current search. Add layer tables in `memory.db` and make `SqliteMemoryStore.insert()` / `batch_insert()` dual-write `raw_memory` and `memory_cards`. Add minimal read APIs on `SqliteMemoryStore` so later packages can move recall to cards behind tests.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `SqliteMemoryStore` and `MemoryService`.

---

## Current Baseline

Phase 2 TraceService package is green:

```bash
pytest tests/test_trace_service.py -q
pytest tests/test_trace_service.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py tests/test_panel_api.py tests/test_router.py -q
pytest -q
```

Expected baseline:

```text
4 passed
120 passed
357 passed, 4 warnings
```

## Files

Create:

- `tests/test_memory_layers.py`

Modify:

- `src/agentmind/storage/db.py`
- `src/agentmind/memory/migrations/runner.py`
- `src/agentmind/memory/sqlite_store.py`

Do not modify in this package:

- `src/agentmind/memory/pipeline/recall.py`
- `src/agentmind/memory/pipeline/assembler.py`
- `src/agentmind/routing/middleware/memory_retriever.py`
- `src/agentmind/panel/server.py`

## Scope

In scope:

- Add idempotent schema for `raw_memory`, `memory_cards`, `sessions`, `result_sets`.
- Ensure schema exists after `initialize_memory_db()` even when a DB is already at schema version 2.
- Dual-write new memory inserts into `raw_memory` and `memory_cards`.
- Add minimal `SqliteMemoryStore.get_raw_memory()` and `get_memory_card()` helpers.
- Prove current search still works through existing compatibility path.

Out of scope:

- Switching recall to `memory_cards`.
- Result set pagination behavior.
- Cold archive lookup.
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
pytest tests/test_memory_layers.py -q
pytest tests/test_memory_layers.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py tests/test_trace_service.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Add layer schema

**Files:**

- Create: `tests/test_memory_layers.py`
- Modify: `src/agentmind/storage/db.py`
- Modify: `src/agentmind/memory/migrations/runner.py`

- [ ] **Step 1: Write failing schema test**

Create `tests/test_memory_layers.py`:

```python
import sqlite3


def test_memory_layer_tables_exist_after_initialize():
    from agentmind.storage.db import DATA_DIR, initialize_memory_db

    initialize_memory_db()

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {"raw_memory", "memory_cards", "sessions", "result_sets"} <= tables
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_layers.py::test_memory_layer_tables_exist_after_initialize -q
```

Expected: FAIL because the layer tables do not exist.

- [ ] **Step 3: Implement idempotent layer schema**

Add an `ensure_memory_layer_tables(db_path: str)` helper in `src/agentmind/memory/migrations/runner.py` and call it from `initialize_memory_db()` after the v2 migration attempt. The helper creates:

- `raw_memory`
- `memory_cards`
- `sessions`
- `result_sets`
- indexes for user/time and card lookup

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_layers.py::test_memory_layer_tables_exist_after_initialize -q
```

Expected: PASS.

---

### Task 2: Dual-write raw memory and memory cards

**Files:**

- Modify: `tests/test_memory_layers.py`
- Modify: `src/agentmind/memory/sqlite_store.py`

- [ ] **Step 1: Add failing dual-write test**

Append to `tests/test_memory_layers.py`:

```python
import pytest

from agentmind.memory.types import MemoryEntry


@pytest.mark.asyncio
async def test_sqlite_store_dual_writes_raw_memory_and_memory_card():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
    entry = MemoryEntry(
        memory_id="m-layer-1",
        content="raw original content",
        summary="card summary",
        source_agent="agent-a",
        source_task_id="task-1",
        user_id="u1",
        tags=["layer", "test"],
    )

    await store.insert(entry)

    raw = await store.get_raw_memory("m-layer-1")
    card = await store.get_memory_card("m-layer-1")
    legacy = await store.get("m-layer-1")

    assert raw["memory_id"] == "m-layer-1"
    assert raw["content"] == "raw original content"
    assert raw["user_id"] == "u1"
    assert card["memory_id"] == "m-layer-1"
    assert card["summary"] == "card summary"
    assert card["tags"] == ["layer", "test"]
    assert legacy is not None
    assert legacy.memory_id == "m-layer-1"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_layers.py::test_sqlite_store_dual_writes_raw_memory_and_memory_card -q
```

Expected: FAIL because `SqliteMemoryStore` does not have layer read helpers and insert does not dual-write.

- [ ] **Step 3: Implement minimal dual-write and helpers**

In `SqliteMemoryStore`:

- Add `_upsert_memory_layers(conn, entry, tags_json, now)`.
- Call it from `_insert_sync()` and `_batch_insert_sync()`.
- Add async `get_raw_memory(memory_id)` / `get_memory_card(memory_id)` methods.
- Parse card tags JSON into a list.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_layers.py::test_sqlite_store_dual_writes_raw_memory_and_memory_card -q
```

Expected: PASS.

---

### Task 3: Prove MemoryService compatibility path remains stable

**Files:**

- Modify: `tests/test_memory_layers.py`

- [ ] **Step 1: Add compatibility test**

Append to `tests/test_memory_layers.py`:

```python
@pytest.mark.asyncio
async def test_memory_service_write_populates_layers_without_changing_search():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "svc-layer-1",
        "content": "memory layers keep compatibility search",
        "summary": "compatibility search",
        "source_agent": "agent-a",
        "source_task_id": "task-1",
        "user_id": "u1",
        "tags": ["compat"],
    })

    rows = await svc.search_memory(query="compatibility", user_id="u1", limit=5)
    card = await svc.store.get_memory_card("svc-layer-1")

    assert any(r["memory_id"] == "svc-layer-1" for r in rows)
    assert card["summary"] == "compatibility search"
```

- [ ] **Step 2: Verify GREEN**

Run:

```bash
pytest tests/test_memory_layers.py::test_memory_service_write_populates_layers_without_changing_search -q
```

Expected: PASS after Task 2. If it fails, fix only the compatibility issue exposed by this test.

---

### Task 4: Package verification

**Files:**

- Modify only the files listed above

- [ ] **Step 1: Run focused and related verification**

Run:

```bash
pytest tests/test_memory_layers.py -q
pytest tests/test_memory_layers.py tests/test_memory.py tests/test_memory_retrieval_eval.py tests/test_session_service.py tests/test_trace_service.py -q
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

- Spec coverage: Covers Phase 2 memory layers first package only: schema, dual-write, minimal layer read API, and compatibility search.
- Intentional gaps: recall does not switch to cards, result sets are schema-only, and cold archive lookup is deferred.
- Placeholder scan: No placeholders remain.
- Type consistency: `MemoryEntry` remains the write input; layer read helpers return plain dicts for compatibility.
