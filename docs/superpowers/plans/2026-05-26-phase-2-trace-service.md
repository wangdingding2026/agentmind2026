# AgentMind Phase 2 Trace Service Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move routing trace records out of user memory so route diagnostics no longer create `memory_entries` rows, while preserving trace lookup compatibility for existing panel/API callers.

**Architecture:** Add `src/agentmind/services/trace_service.py` backed by `trace.db` and a `routing_traces` table. `TraceRecorder` becomes a compatibility adapter that delegates to `TraceService`. `TraceService.get_trace()` first reads new trace storage, then falls back to legacy `memory_entries` rows named `trace-{trace_id}` so old trace data remains visible during migration.

**Tech Stack:** Python 3.12, SQLite, pytest, FastAPI TestClient.

---

## Current Baseline

Phase 2 SessionService package is green:

```bash
pytest tests/test_session_service.py -q
pytest tests/test_session_service.py tests/test_memory_service_convergence.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest tests/test_attach.py tests/test_pipeline_executors.py tests/test_feishu_path.py -q
pytest -q
```

Expected baseline:

```text
4 passed
85 passed
66 passed
353 passed, 4 warnings
```

## Files

Create:

- `src/agentmind/services/trace_service.py`
- `tests/test_trace_service.py`

Modify:

- `src/agentmind/routing/side_effects/trace_recorder.py`
- `src/agentmind/panel/server.py`
- `tests/test_pipeline_executors.py`
- `tests/test_e2e_scenarios.py`

Do not modify in this package:

- `src/agentmind/services/session_service.py`
- `src/agentmind/storage/memory.py`
- `src/agentmind/memory/service.py`
- `src/agentmind/services/routing_service.py`

## Scope

In scope:

- Persist routing decision traces to `trace.db`.
- Preserve `TraceRecorder.record_decision()` and `TraceRecorder.get_trace()` public methods as adapters.
- Preserve legacy lookup from `memory_entries` for old `trace-*` records.
- Move panel `/routing/trace/{trace_id}` lookup to `TraceService`.

Out of scope:

- AuditService.
- Strategy run instrumentation beyond a minimal API method.
- Migrating existing legacy trace rows into `trace.db`.
- Removing discussion/task memory writes.

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
pytest tests/test_trace_service.py -q
pytest tests/test_trace_service.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py tests/test_panel_api.py -q
pytest -q
```

---

### Task 1: Add TraceService storage and legacy fallback

**Files:**

- Create: `tests/test_trace_service.py`
- Create: `src/agentmind/services/trace_service.py`

- [ ] **Step 1: Write failing tests for trace storage outside memory**

Create `tests/test_trace_service.py`:

```python
import json
import sqlite3

import pytest

from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision


def _decision() -> RoutingDecision:
    return RoutingDecision(
        agent_id="a1",
        strategy="explicit",
        confidence=0.85,
        fallback_chain=["a2"],
        reply_text="ok",
        context=RoutingContext(
            identity=RequestIdentity(trace_id="t1", user_id="u1"),
            raw_message="hello",
            candidates=["a1", "a2"],
            security_flagged=False,
        ),
    )


@pytest.mark.asyncio
async def test_trace_service_records_decision_outside_memory_db():
    from agentmind.services.trace_service import TraceService
    from agentmind.storage.db import DATA_DIR

    svc = TraceService()
    await svc.record_decision("t1", _decision(), user_id="u1")

    trace = await svc.get_trace("t1")

    assert trace is not None
    assert trace["trace_id"] == "t1"
    assert trace["agent_id"] == "a1"
    assert trace["strategy"] == "explicit"
    assert trace["summary"] == "[explicit] -> a1 (conf=0.85)"
    content = json.loads(trace["content"])
    assert content["raw_message"] == "hello"

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        row = conn.execute(
            "SELECT memory_id FROM memory_entries WHERE memory_id=?",
            ("trace-t1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.asyncio
async def test_trace_service_reads_legacy_memory_trace():
    from agentmind.services.trace_service import TraceService
    from agentmind.storage.db import DATA_DIR

    conn = sqlite3.connect(str(DATA_DIR / "memory.db"))
    try:
        conn.execute(
            """INSERT INTO memory_entries
               (memory_id, content, summary, source_agent, source_task_id, created_at, access_level, tags, user_id)
               VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)""",
            (
                "trace-old",
                '{"agent_id": "legacy"}',
                "[legacy] -> old (conf=0.4)",
                "agentmind",
                "old",
                "private",
                '["routing_trace"]',
                "u1",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    trace = await TraceService().get_trace("old")

    assert trace is not None
    assert trace["summary"] == "[legacy] -> old (conf=0.4)"
    assert trace["memory_id"] == "trace-old"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_trace_service.py::test_trace_service_records_decision_outside_memory_db tests/test_trace_service.py::test_trace_service_reads_legacy_memory_trace -q
```

Expected: FAIL because `agentmind.services.trace_service` does not exist.

- [ ] **Step 3: Implement minimal TraceService**

Create `src/agentmind/services/trace_service.py` with:

```python
"""TraceService — persistent routing trace storage outside user memory."""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class TraceService:
    def __init__(self, db_path: str = ""):
        if db_path:
            self._db_path = db_path
        else:
            from agentmind.storage.db import DATA_DIR
            self._db_path = str(DATA_DIR / "trace.db")
        self._ensure_schema()

    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS routing_traces (
                    trace_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    user_id TEXT DEFAULT '',
                    agent_id TEXT DEFAULT '',
                    strategy TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    fallback_chain TEXT DEFAULT '[]',
                    reply_text TEXT DEFAULT '',
                    raw_message TEXT DEFAULT '',
                    candidates TEXT DEFAULT '[]',
                    security_flagged INTEGER DEFAULT 0,
                    payload TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_routing_traces_created ON routing_traces(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_routing_traces_user ON routing_traces(user_id, created_at DESC)")
            conn.commit()
        finally:
            conn.close()

    async def record_decision(self, trace_id: str, decision, user_id: str = ""):
        await asyncio.to_thread(self._record_decision_sync, trace_id, decision, user_id)

    def _record_decision_sync(self, trace_id: str, decision, user_id: str = ""):
        context = decision.context
        payload = {
            "agent_id": decision.agent_id,
            "strategy": decision.strategy,
            "confidence": decision.confidence,
            "fallback_chain": decision.fallback_chain,
            "reply_text": decision.reply_text[:200] if decision.reply_text else "",
            "raw_message": context.raw_message[:500] if context else "",
            "candidates": context.candidates if context else [],
            "security_flagged": context.security_flagged if context else False,
        }
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO routing_traces
                   (trace_id, created_at, user_id, agent_id, strategy, confidence,
                    fallback_chain, reply_text, raw_message, candidates, security_flagged, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace_id,
                    _now_sqlite(),
                    user_id,
                    payload["agent_id"],
                    payload["strategy"],
                    float(payload["confidence"] or 0.0),
                    json.dumps(payload["fallback_chain"], ensure_ascii=False),
                    payload["reply_text"],
                    payload["raw_message"],
                    json.dumps(payload["candidates"], ensure_ascii=False),
                    1 if payload["security_flagged"] else 0,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def record_strategy_run(self, trace_id: str, strategy: str, payload: dict | None = None):
        payload = payload or {}
        await asyncio.to_thread(self._record_strategy_run_sync, trace_id, strategy, payload)

    def _record_strategy_run_sync(self, trace_id: str, strategy: str, payload: dict):
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO routing_traces
                   (trace_id, created_at, strategy, payload)
                   VALUES (?, ?, ?, ?)""",
                (trace_id, _now_sqlite(), strategy, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_trace(self, trace_id: str) -> dict | None:
        trace = await asyncio.to_thread(self._get_trace_sync, trace_id)
        if trace is not None:
            return trace
        return await asyncio.to_thread(self._get_legacy_memory_trace_sync, trace_id)

    def _get_trace_sync(self, trace_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM routing_traces WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
            if not row:
                return None
            return self._format_trace(dict(row))
        finally:
            conn.close()

    def _format_trace(self, row: dict) -> dict:
        payload = json.loads(row.get("payload") or "{}")
        summary = f"[{row.get('strategy', '')}] -> {row.get('agent_id', '')} (conf={row.get('confidence', 0.0)})"
        row["content"] = json.dumps(payload, ensure_ascii=False)
        row["summary"] = summary
        row["memory_id"] = f"trace-{row['trace_id']}"
        row["source_agent"] = "agentmind"
        row["source_task_id"] = row["trace_id"]
        row["tags"] = ["routing_trace"] + ([f"user:{row['user_id']}"] if row.get("user_id") else [])
        row["access_level"] = "private"
        return row

    def _get_legacy_memory_trace_sync(self, trace_id: str) -> dict | None:
        try:
            from agentmind.storage.memory import _get_memory_conn
            conn = _get_memory_conn()
        except Exception:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE memory_id=? LIMIT 1",
                (f"trace-{trace_id}",),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    async def query_traces(self, limit: int = 20, user_id: str = "") -> list[dict]:
        return await asyncio.to_thread(self._query_traces_sync, limit, user_id)

    def _query_traces_sync(self, limit: int = 20, user_id: str = "") -> list[dict]:
        conn = self._get_conn()
        try:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM routing_traces WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM routing_traces ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._format_trace(dict(r)) for r in rows]
        finally:
            conn.close()
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_trace_service.py::test_trace_service_records_decision_outside_memory_db tests/test_trace_service.py::test_trace_service_reads_legacy_memory_trace -q
```

Expected: PASS.

---

### Task 2: Make TraceRecorder an adapter over TraceService

**Files:**

- Modify: `tests/test_trace_service.py`
- Modify: `src/agentmind/routing/side_effects/trace_recorder.py`
- Modify: `tests/test_pipeline_executors.py`
- Modify: `tests/test_e2e_scenarios.py`

- [ ] **Step 1: Add failing adapter test**

Append to `tests/test_trace_service.py`:

```python
@pytest.mark.asyncio
async def test_trace_recorder_delegates_to_trace_service(monkeypatch):
    from agentmind.routing.side_effects.trace_recorder import TraceRecorder
    import agentmind.routing.side_effects.trace_recorder as trace_recorder

    calls = []

    class FakeTraceService:
        async def record_decision(self, trace_id, decision, user_id=""):
            calls.append(("record", trace_id, decision.agent_id, user_id))

        async def get_trace(self, trace_id):
            calls.append(("get", trace_id))
            return {"trace_id": trace_id}

    monkeypatch.setattr(trace_recorder, "TraceService", FakeTraceService)

    await TraceRecorder.record_decision("t1", _decision(), "u1")
    assert await TraceRecorder.get_trace("t1") == {"trace_id": "t1"}
    assert ("record", "t1", "a1", "u1") in calls
    assert ("get", "t1") in calls
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_trace_service.py::test_trace_recorder_delegates_to_trace_service -q
```

Expected: FAIL because `trace_recorder.py` does not expose `TraceService` and still imports `write_memory`.

- [ ] **Step 3: Implement TraceRecorder adapter**

Modify `src/agentmind/routing/side_effects/trace_recorder.py`:

```python
import logging

from agentmind.services.trace_service import TraceService

logger = logging.getLogger("agentmind")


class TraceRecorder:
    """L4 side effect adapter for routing trace persistence."""

    @staticmethod
    async def record_decision(trace_id: str, decision, user_id: str = ""):
        try:
            await TraceService().record_decision(trace_id, decision, user_id)
        except Exception:
            logger.debug("记录 routing trace 失败", exc_info=True)

    @staticmethod
    async def get_trace(trace_id: str) -> dict | None:
        try:
            return await TraceService().get_trace(trace_id)
        except Exception:
            logger.debug("查询 routing trace 失败", exc_info=True)
            return None
```

Update existing tests in `tests/test_pipeline_executors.py` and `tests/test_e2e_scenarios.py` to assert TraceService delegation instead of `write_memory`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_trace_service.py::test_trace_recorder_delegates_to_trace_service tests/test_pipeline_executors.py::TestTraceRecorder::test_record_and_get tests/test_e2e_scenarios.py::TestScenarioTraceRecording::test_decision_recorded -q
```

Expected: PASS.

---

### Task 3: Move panel trace lookup to TraceService

**Files:**

- Modify: `tests/test_trace_service.py`
- Modify: `src/agentmind/panel/server.py`

- [ ] **Step 1: Add failing panel test**

Append to `tests/test_trace_service.py`:

```python
def test_panel_routing_trace_uses_trace_service(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agentmind.panel.server import create_panel_router

    class FakeTraceService:
        async def get_trace(self, trace_id):
            return {"trace_id": trace_id, "summary": "from service"}

    monkeypatch.setattr("agentmind.panel.server.TraceService", FakeTraceService, raising=False)

    app = FastAPI()
    app.include_router(create_panel_router(), prefix="/panel/api")
    client = TestClient(app)

    resp = client.get("/panel/api/routing/trace/t1")

    assert resp.status_code == 200
    assert resp.json()["summary"] == "from service"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_trace_service.py::test_panel_routing_trace_uses_trace_service -q
```

Expected: FAIL because panel route still imports `TraceRecorder` directly.

- [ ] **Step 3: Implement panel migration**

Modify `src/agentmind/panel/server.py`:

```python
from agentmind.services.trace_service import TraceService
```

Then in `/routing/trace/{trace_id}`:

```python
trace = await TraceService().get_trace(trace_id)
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_trace_service.py::test_panel_routing_trace_uses_trace_service -q
```

Expected: PASS.

---

### Task 4: Package verification

**Files:**

- Modify only the files listed above

- [ ] **Step 1: Run focused and related verification**

Run:

```bash
pytest tests/test_trace_service.py -q
pytest tests/test_trace_service.py tests/test_pipeline_executors.py tests/test_e2e_scenarios.py tests/test_panel_api.py -q
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

- Spec coverage: Covers Phase 2 package 3 only: routing trace storage split from memory, TraceRecorder adapter, panel lookup migration, and legacy memory trace read compatibility.
- Intentional gaps: AuditService, strategy run deep instrumentation, migration of old rows into trace.db, and trace UI expansion are deferred.
- Placeholder scan: No placeholder tasks remain.
- Type consistency: `TraceService.record_decision`, `get_trace`, `query_traces`, and `TraceRecorder` methods keep async usage consistent.
