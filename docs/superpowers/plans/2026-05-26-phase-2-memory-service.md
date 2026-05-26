# AgentMind Phase 2 Memory Service Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `MemoryService` the business-facing entrypoint for memory write, search, stats, cleanup, writer side effects, and retrieval side effects while preserving existing behavior.

**Architecture:** Keep `src/agentmind/storage/memory.py` as the legacy compatibility surface for now, but make every public operation able to delegate to `MemoryService` under the existing v4 memory flag. Then move routing-side memory write and retrieve code to call `MemoryService` directly, leaving old helpers only as fallback compatibility. Do not move trace storage, do not add conflict detection, and do not persist sessions in this package.

**Tech Stack:** Python 3.12, SQLite, pytest, pytest-asyncio, existing AgentMind memory v4 pipeline.

---

## Current Baseline

Phase 1 routing package is green:

```bash
pytest -q
```

Expected baseline:

```text
345 passed, 4 warnings
```

## Files

Create:

- `tests/test_memory_service_convergence.py`

Modify:

- `src/agentmind/storage/memory.py`
- `src/agentmind/routing/side_effects/memory_writer.py`
- `src/agentmind/routing/middleware/memory_retriever.py`

Do not modify in this package:

- `src/agentmind/routing/side_effects/trace_recorder.py`
- `src/agentmind/panel/server.py`
- `src/agentmind/memory/sqlite_store.py`
- `src/agentmind/memory/pipeline/*`

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
pytest tests/test_memory_service_convergence.py -q
pytest tests/test_memory.py tests/test_pipeline_executors.py tests/test_memory_retrieval_eval.py -q
pytest -q
```

---

### Task 1: Complete v4 delegation for legacy public memory APIs

**Files:**

- Create: `tests/test_memory_service_convergence.py`
- Modify: `src/agentmind/storage/memory.py`

- [ ] **Step 1: Write failing tests proving stats and cleanup delegate when v4 is enabled**

Create `tests/test_memory_service_convergence.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_legacy_stats_delegates_to_memory_service_when_v4_enabled(monkeypatch):
    from agentmind.storage import memory as legacy_memory

    calls = []

    class FakeMemoryService:
        async def get_memory_stats(self):
            calls.append("stats")
            return {"total": 7}

    monkeypatch.setattr(legacy_memory, "_use_v4_memory_store", lambda: True)
    monkeypatch.setattr("agentmind.memory.service.MemoryService", FakeMemoryService)

    assert await legacy_memory.get_memory_stats() == {"total": 7}
    assert calls == ["stats"]


@pytest.mark.asyncio
async def test_legacy_cleanup_delegates_to_memory_service_when_v4_enabled(monkeypatch):
    from agentmind.storage import memory as legacy_memory

    calls = []

    class FakeMemoryService:
        async def cleanup_memory(self, retention_days=30):
            calls.append(retention_days)
            return 3

    monkeypatch.setattr(legacy_memory, "_use_v4_memory_store", lambda: True)
    monkeypatch.setattr("agentmind.memory.service.MemoryService", FakeMemoryService)

    assert await legacy_memory.cleanup_memory(retention_days=14) == 3
    assert calls == [14]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_service_convergence.py -q
```

Expected: FAIL because `get_memory_stats()` and `cleanup_memory()` still call legacy sync helpers even when v4 is enabled.

- [ ] **Step 3: Implement minimal delegation**

Modify `src/agentmind/storage/memory.py`:

```python
async def get_memory_stats() -> dict:
    if _use_v4_memory_store():
        from agentmind.memory.service import MemoryService
        return await MemoryService().get_memory_stats()
    return await asyncio.to_thread(_get_memory_stats_sync)


async def cleanup_memory(retention_days: int = 30) -> int:
    """清理超过 retention_days 天的记忆，返回删除数"""
    if _use_v4_memory_store():
        from agentmind.memory.service import MemoryService
        return await MemoryService().cleanup_memory(retention_days=retention_days)
    return await asyncio.to_thread(_cleanup_memory_sync, retention_days)
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_service_convergence.py -q
```

Expected: PASS.

---

### Task 2: Move MemoryWriter to MemoryService as the primary path

**Files:**

- Modify: `tests/test_memory_service_convergence.py`
- Modify: `src/agentmind/routing/side_effects/memory_writer.py`

- [ ] **Step 1: Add failing tests for MemoryWriter service usage**

Append:

```python
@pytest.mark.asyncio
async def test_memory_writer_uses_memory_service_for_task_memory(monkeypatch):
    from agentmind.routing.side_effects.memory_writer import MemoryWriter

    writes = []

    class FakeMemoryService:
        def add_to_working_memory(self, user_id, role, content):
            pass

        async def write_memory(self, entry, generate_embedding=True, user_id=""):
            writes.append((entry, user_id))
            return 1

    monkeypatch.setattr("agentmind.routing.side_effects.memory_writer.MemoryService", FakeMemoryService)
    monkeypatch.setattr(MemoryWriter, "_extract_facts", staticmethod(lambda *args, **kwargs: None))

    await MemoryWriter.write_task("tr-1", "agent-a", "hello", "world", user_id="u1")

    assert writes
    assert writes[0][0]["memory_id"] == "task-tr-1"
    assert writes[0][1] == "u1"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_service_convergence.py::test_memory_writer_uses_memory_service_for_task_memory -q
```

Expected: FAIL because `memory_writer.py` does not expose module-level `MemoryService` and only uses the service under `_use_v4()`.

- [ ] **Step 3: Implement minimal writer migration**

Modify `src/agentmind/routing/side_effects/memory_writer.py`:

```python
from agentmind.memory.service import MemoryService
```

Then in `write_task()`, use:

```python
svc = MemoryService()
await svc.write_memory({...}, user_id=user_id)
```

Keep the broad `try/except` best-effort behavior unchanged. Remove the `_use_v4()` branch for task memory writes, but keep `_use_v4()` available for fact extraction until the fact test is added.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_service_convergence.py::test_memory_writer_uses_memory_service_for_task_memory -q
```

Expected: PASS.

---

### Task 3: Move MemoryRetriever fallback reads to MemoryService

**Files:**

- Modify: `tests/test_memory_service_convergence.py`
- Modify: `src/agentmind/routing/middleware/memory_retriever.py`

- [ ] **Step 1: Add failing tests for retriever service usage**

Append:

```python
@pytest.mark.asyncio
async def test_memory_retriever_uses_memory_service_search_for_fallback(monkeypatch):
    from agentmind.routing.middleware.memory_retriever import MemoryRetriever

    calls = []

    class FakeMemoryService:
        async def retrieve(self, message, user_id="", settings=None):
            return {"assembled_context": "", "recall_items": [], "steps": ["v4_disabled"]}

        async def search_memory(self, query="", user_id="", source_agent="", tags=None, access_levels=None, limit=10):
            calls.append((query, user_id, limit))
            return [{"memory_id": f"m-{len(calls)}", "content": query or "recent"}]

    monkeypatch.setattr("agentmind.routing.middleware.memory_retriever.MemoryService", FakeMemoryService)
    monkeypatch.setattr("agentmind.routing.middleware.memory_retriever._use_v4_retrieval", lambda: False)

    rows = await MemoryRetriever().retrieve("hello world", "u1", limit=2)

    assert rows
    assert calls
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_memory_service_convergence.py::test_memory_retriever_uses_memory_service_search_for_fallback -q
```

Expected: FAIL because `memory_retriever.py` imports and calls `storage.memory.search_memory` directly.

- [ ] **Step 3: Implement minimal retriever migration**

Modify `src/agentmind/routing/middleware/memory_retriever.py`:

```python
from agentmind.memory.service import MemoryService
```

Use `svc = MemoryService()` for both v4 retrieval and fallback `search_memory()` calls. Preserve date-filter behavior and old return shape.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_memory_service_convergence.py::test_memory_retriever_uses_memory_service_search_for_fallback -q
```

Expected: PASS.

---

### Task 4: Package verification

**Files:**

- Modify only the files listed above

- [ ] **Step 1: Run package verification**

Run:

```bash
pytest tests/test_memory_service_convergence.py -q
pytest tests/test_memory.py tests/test_pipeline_executors.py tests/test_memory_retrieval_eval.py -q
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

- Spec coverage: Covers Phase 2 package 1 only: public memory API delegation plus MemoryWriter and MemoryRetriever service usage.
- Intentional gaps: trace split, conflict detection, AuditService, panel memory delete migration, and session persistence are deferred.
- Placeholder scan: No placeholder tasks remain.
- Type consistency: `MemoryService.write_memory`, `search_memory`, `get_memory_stats`, and `cleanup_memory` are used with their existing signatures.
