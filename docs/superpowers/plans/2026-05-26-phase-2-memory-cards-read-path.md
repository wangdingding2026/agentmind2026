# AgentMind Phase 2 Memory Cards Read Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, tested read path that searches `memory_cards` directly so Phase 2 can move retrieval toward card-first recall without adding new behavior to legacy `memory_entries`.

**Architecture:** Keep `memory_entries` as the compatibility write/search source for the current public `search_memory()` path in this package, but introduce `SqliteMemoryStore.search_memory_cards(SearchQuery)` and `MemoryService.search_memory_cards(...)` as the target-architecture API. Card search reads only from `memory_cards`, searches `card_text`/`summary`, applies the existing `SearchQuery` filters, parses JSON fields, and returns deterministic scores based on textual match, importance, and recency. The next package can switch default recall/search to this API once quality gates are in place.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `SearchQuery`, `MemoryEntry`, `SqliteMemoryStore`, `MemoryService`, and Phase 2 memory layer tables.

---

## Current Baseline

Previous Phase 2 package was green:

```bash
pytest tests/test_memory_layers_semantic.py -q
pytest tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

Expected baseline:

```text
3 passed
94 passed
48 passed
363 passed, 4 warnings
```

## Files

Create:

- `tests/test_memory_cards_read_path.py`

Modify:

- `src/agentmind/memory/sqlite_store.py`
- `src/agentmind/memory/service.py`

Do not modify in this package:

- `src/agentmind/memory/pipeline/recall.py`
- `src/agentmind/routing/middleware/memory_retriever.py`
- `src/agentmind/storage/memory.py`
- `src/agentmind/memory/migrations/runner.py`

## Scope

In scope:

- Add `SqliteMemoryStore.search_memory_cards(SearchQuery)`.
- Add card filtering for `user_id`, `access_levels`, `memory_types`, `tags`, `conversation_id`/`session_id`, and time range.
- Search against `memory_cards.card_text` and `memory_cards.summary`.
- Return parsed card dictionaries containing `raw_memory_id`, `card_text`, `source_refs`, `score_metadata`, and `_score`.
- Add `MemoryService.search_memory_cards(...)` as an explicit public service entry.
- Add a small deterministic evaluation smoke test based on existing memory retrieval fixture categories.

Out of scope:

- Switching `MemoryService.search_memory()` to card search.
- Switching routing recall middleware or v4 `RetrievalPipeline` to card search.
- Adding card FTS/vector indexes.
- Backfilling old `memory_entries` rows into card tables.
- Conflict detection, result-set navigation, audit, or CPE policy.

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
pytest tests/test_memory_cards_read_path.py -q
pytest tests/test_memory_cards_read_path.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest tests/test_router.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Add store-level card search API

**Files:**

- Create: `tests/test_memory_cards_read_path.py`
- Modify: `src/agentmind/memory/sqlite_store.py`

- [ ] **Step 1: Write failing store API tests**

Create `tests/test_memory_cards_read_path.py`:

```python
import pytest

from agentmind.memory.types import MemoryEntry, MemoryType, SearchQuery


@pytest.mark.asyncio
async def test_sqlite_store_search_memory_cards_reads_card_text_not_legacy_content():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
    await store.insert(MemoryEntry(
        memory_id="card-read-1",
        content="large raw transcript contains implementation chatter only",
        summary="Memory cards are the retrieval surface",
        user_id="u_cards",
        source_agent="codex",
        source_task_id="task-card",
        memory_type=MemoryType.SEMANTIC,
        conversation_id="sess-cards",
        importance=0.9,
        tags=["architecture", "memory"],
        access_level="shared",
        created_at="2026-05-25 10:00:00",
    ))

    rows = await store.search_memory_cards(SearchQuery(
        query_text="retrieval surface",
        user_id="u_cards",
        limit=5,
    ))

    assert [r["memory_id"] for r in rows] == ["card-read-1"]
    assert rows[0]["raw_memory_id"] == "card-read-1"
    assert rows[0]["card_text"].startswith("Memory cards are the retrieval surface")
    assert rows[0]["source_refs"]["source_agent"] == "codex"
    assert rows[0]["score_metadata"]["memory_type"] == "semantic"
    assert rows[0]["_route"] == "memory_cards"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_sqlite_store_search_memory_cards_reads_card_text_not_legacy_content -q
```

Expected: FAIL with `AttributeError` because `SqliteMemoryStore.search_memory_cards` does not exist.

- [ ] **Step 3: Implement minimal card search**

Add to `src/agentmind/memory/sqlite_store.py`:

- `async def search_memory_cards(self, query: SearchQuery) -> list[dict]`
- `_search_memory_cards_sync(self, query: SearchQuery) -> list[dict]`
- `_build_card_filter_clause(self, query: SearchQuery) -> tuple[str, list]`
- `_row_to_memory_card(self, row) -> dict`
- `_score_memory_card(self, row, query: SearchQuery) -> float`

Implementation rules:

- Query `memory_cards` only.
- If `query.query_text` is present, match `(card_text LIKE ? OR summary LIKE ?)`.
- If query text is empty, return recent cards by `created_at DESC`.
- Sort by `_score DESC, created_at DESC, memory_id ASC`.
- Parse `tags`, `source_refs`, and `score_metadata` as JSON.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_sqlite_store_search_memory_cards_reads_card_text_not_legacy_content -q
```

Expected: PASS.

---

### Task 2: Add filters and deterministic ordering

**Files:**

- Modify: `tests/test_memory_cards_read_path.py`
- Modify: `src/agentmind/memory/sqlite_store.py`

- [ ] **Step 1: Add failing filter/ranking test**

Append:

```python
@pytest.mark.asyncio
async def test_sqlite_store_search_memory_cards_filters_and_orders_results():
    from agentmind.memory.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore()
    entries = [
        MemoryEntry(
            memory_id="card-rank-old-important",
            content="raw alpha",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.SEMANTIC,
            conversation_id="sess-filter",
            importance=0.95,
            tags=["database", "trace"],
            access_level="shared",
            created_at="2026-05-24 09:00:00",
        ),
        MemoryEntry(
            memory_id="card-rank-new-less-important",
            content="raw beta",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.SEMANTIC,
            conversation_id="sess-filter",
            importance=0.40,
            tags=["database", "trace"],
            access_level="shared",
            created_at="2026-05-25 09:00:00",
        ),
        MemoryEntry(
            memory_id="card-rank-private",
            content="raw private",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.SEMANTIC,
            conversation_id="sess-filter",
            importance=0.99,
            tags=["database", "trace"],
            access_level="private",
            created_at="2026-05-26 09:00:00",
        ),
        MemoryEntry(
            memory_id="card-rank-other-session",
            content="raw other",
            summary="database boundary card",
            user_id="u_filter",
            memory_type=MemoryType.EPISODIC,
            conversation_id="sess-other",
            importance=1.0,
            tags=["database", "trace"],
            access_level="shared",
            created_at="2026-05-26 10:00:00",
        ),
    ]
    await store.batch_insert(entries)

    rows = await store.search_memory_cards(SearchQuery(
        query_text="database boundary",
        user_id="u_filter",
        memory_types=[MemoryType.SEMANTIC],
        access_levels=["shared"],
        tags=["trace"],
        conversation_id="sess-filter",
        limit=10,
    ))

    assert [r["memory_id"] for r in rows] == [
        "card-rank-old-important",
        "card-rank-new-less-important",
    ]
    assert rows[0]["_score"] > rows[1]["_score"]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_sqlite_store_search_memory_cards_filters_and_orders_results -q
```

Expected: FAIL because filters/ranking are incomplete.

- [ ] **Step 3: Implement filters and ranking**

Update `_build_card_filter_clause()` and `_score_memory_card()`:

- `user_id`: exact match.
- `access_levels`: `IN (...)`.
- `memory_types`: enum `.value`.
- `tags`: JSON text LIKE, OR semantics.
- `conversation_id`: match `(conversation_id = ? OR session_id = ?)`.
- `time_range_start` / `time_range_end`: `created_at` bounds.
- Score weights:
  - `1.0` if query text matches `summary`.
  - `0.7` if query text matches `card_text`.
  - plus `0.5 * importance`.
  - plus small recency tiebreaker derived from `created_at`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_sqlite_store_search_memory_cards_filters_and_orders_results -q
```

Expected: PASS.

---

### Task 3: Add MemoryService card search entry

**Files:**

- Modify: `tests/test_memory_cards_read_path.py`
- Modify: `src/agentmind/memory/service.py`

- [ ] **Step 1: Add failing service API test**

Append:

```python
@pytest.mark.asyncio
async def test_memory_service_search_memory_cards_returns_card_shape_without_cutting_default_search():
    from agentmind.memory.service import MemoryService

    svc = MemoryService()
    await svc.write_memory({
        "memory_id": "svc-card-search-1",
        "content": "raw content about card-first retrieval",
        "summary": "card-first retrieval path",
        "source_agent": "codex",
        "source_task_id": "task-service-card",
        "user_id": "u_service_cards",
        "tags": ["memory", "cards"],
        "access_level": "shared",
    })

    card_rows = await svc.search_memory_cards(
        query="card-first retrieval",
        user_id="u_service_cards",
        source_agent="codex",
        tags=["cards"],
        limit=5,
    )
    default_rows = await svc.search_memory(
        query="card-first retrieval",
        user_id="u_service_cards",
        limit=5,
    )

    assert [r["memory_id"] for r in card_rows] == ["svc-card-search-1"]
    assert "card_text" in card_rows[0]
    assert card_rows[0]["raw_memory_id"] == "svc-card-search-1"
    assert card_rows[0]["_route"] == "memory_cards"
    assert any(r["memory_id"] == "svc-card-search-1" for r in default_rows)
    assert all(r.get("_route") != "memory_cards" for r in default_rows)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_memory_service_search_memory_cards_returns_card_shape_without_cutting_default_search -q
```

Expected: FAIL with `AttributeError` because `MemoryService.search_memory_cards` does not exist.

- [ ] **Step 3: Implement service entry**

Add `MemoryService.search_memory_cards(...)` with parameters matching `search_memory(...)` plus optional `memory_types`, `conversation_id`, and time range. It must:

- Build `SearchQuery`.
- Call `self._store.search_memory_cards(search_query)`.
- Apply `source_agent` filter at the service layer for parity with `search_memory()`.
- Return dictionaries unchanged except for final `limit`.
- Not call or modify `search_memory()`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_memory_service_search_memory_cards_returns_card_shape_without_cutting_default_search -q
```

Expected: PASS.

---

### Task 4: Add retrieval fixture smoke coverage

**Files:**

- Modify: `tests/test_memory_cards_read_path.py`

- [ ] **Step 1: Add failing fixture smoke test**

Append:

```python
from pathlib import Path

import yaml


def _fixture_cases_by_category():
    fixture_path = Path(__file__).parent / "fixtures" / "memory_retrieval_cases.yaml"
    data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    return {case["category"]: case for case in data["cases"]}


@pytest.mark.asyncio
async def test_memory_cards_search_smoke_covers_topic_date_and_agent_fixture_cases():
    from agentmind.memory.service import MemoryService

    cases = _fixture_cases_by_category()
    svc = MemoryService()

    selected = [
        cases["topic_query"],
        cases["date_query"],
        cases["agent_source"],
    ]

    for case in selected:
        seed = case["seed_memories"][0]
        memory_id = f"fixture-card-{case['category']}"
        await svc.write_memory({
            "memory_id": memory_id,
            "content": seed["content"],
            "summary": seed["content"],
            "source_agent": seed.get("agent_id", seed.get("role", "")),
            "source_task_id": case["id"],
            "user_id": seed["user_id"],
            "conversation_id": seed["session_id"],
            "tags": seed.get("tags", []),
            "created_at": seed.get("created_at", ""),
            "access_level": seed.get("access_level", "shared"),
        })

    topic_rows = await svc.search_memory_cards(
        query="MemoryService 唯一入口",
        user_id="u_eval",
        tags=["memory"],
        limit=3,
    )
    date_rows = await svc.search_memory_cards(
        query="飞书 WebSocket 重连",
        user_id="u_eval",
        time_range_start="2026-05-25",
        time_range_end="2026-05-25T23:59:59+08:00",
        limit=3,
    )
    agent_rows = await svc.search_memory_cards(
        query="数据库建议",
        user_id="u_eval",
        source_agent="codex",
        limit=3,
    )

    assert any(r["source_task_id"] == "topic-query-memory-service" for r in topic_rows)
    assert any(r["source_task_id"] == "date-filter-yesterday" for r in date_rows)
    assert any(r["source_task_id"] == "agent-source-codex" for r in agent_rows)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_memory_cards_search_smoke_covers_topic_date_and_agent_fixture_cases -q
```

Expected: FAIL until service card search exists and filters are complete.

- [ ] **Step 3: Keep implementation minimal**

If Task 1-3 implementation already satisfies this test, do not add production code. If it fails because date strings compare incorrectly, normalize SQLite date strings only in the write path already used for cards, not by adding legacy table behavior.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_cards_read_path.py::test_memory_cards_search_smoke_covers_topic_date_and_agent_fixture_cases -q
```

Expected: PASS.

---

### Task 5: Package and regression verification

**Files:**

- Verify only.

- [ ] **Step 1: Run focused package tests**

Run:

```bash
pytest tests/test_memory_cards_read_path.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run memory-related tests**

Run:

```bash
pytest tests/test_memory_cards_read_path.py tests/test_memory_layers.py tests/test_memory_layers_semantic.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run full suite**

Run:

```bash
pytest -q
```

Expected: all tests pass.

