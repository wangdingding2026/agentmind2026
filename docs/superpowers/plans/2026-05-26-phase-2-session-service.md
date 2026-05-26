# AgentMind Phase 2 Session Service Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `MemoryService` session state and working memory out of class-level process memory into a persistent `SessionService`, while preserving `/new`, force-new conversation, and current-session working-memory behavior.

**Architecture:** Add `src/agentmind/services/session_service.py` backed by `memory.db`. The service owns active session ids, one-shot `force_new_next`, and recent working memory. `MemoryService` remains the public compatibility facade for `new_session()`, `get_active_session()`, `add_to_working_memory()`, and `get_working_memory()`, but delegates storage and state to `SessionService`.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `SqliteMemoryStore` / `ConversationMerger`.

---

## Current Baseline

Phase 2 MemoryService convergence is green:

```bash
pytest tests/test_memory_service_convergence.py -q
pytest tests/test_memory.py tests/test_pipeline_executors.py tests/test_memory_retrieval_eval.py -q
pytest -q
```

Expected baseline:

```text
4 passed
112 passed
349 passed, 4 warnings
```

## Files

Create:

- `src/agentmind/services/session_service.py`
- `tests/test_session_service.py`

Modify:

- `src/agentmind/memory/service.py`

Do not modify in this package:

- `src/agentmind/routing/side_effects/session_registry.py`
- `src/agentmind/api/attach_registry.py`
- `src/agentmind/panel/server.py`
- `src/agentmind/services/routing_service.py`

## Scope

In scope:

- Persist active session id per user.
- Persist and consume `force_new_next` across service instances.
- Persist working memory and keep the existing max 20-message cap.
- Clear working memory on `/new`.
- Keep `MemoryService` method signatures unchanged.

Out of scope:

- Persist discussion state.
- Persist attach bindings.
- TraceService split.
- Conflict detection or AuditService.
- Panel session endpoint migration.

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
pytest tests/test_session_service.py -q
pytest tests/test_session_service.py tests/test_memory_service_convergence.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
pytest -q
```

---

### Task 1: Add persistent SessionService

**Files:**

- Create: `tests/test_session_service.py`
- Create: `src/agentmind/services/session_service.py`

- [ ] **Step 1: Write failing tests for persistent sessions and working memory**

Create `tests/test_session_service.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_session_service_new_session_persists_force_flag_and_clears_working_memory():
    from agentmind.services.session_service import SessionService

    svc = SessionService()
    svc.add_to_working_memory("u1", "user", "hello")
    svc.add_to_working_memory("u1", "assistant", "world")
    assert svc.get_working_memory("u1", limit=1)

    sid = await svc.new_session("u1")

    assert sid.startswith("sess-")
    assert svc.get_active_session("u1") == sid
    assert svc.get_working_memory("u1", limit=1) == []
    assert svc.consume_force_new("u1") is True
    assert svc.consume_force_new("u1") is False

    restarted = SessionService()
    assert restarted.get_active_session("u1") == sid


def test_session_service_recovers_working_memory_after_new_instance():
    from agentmind.services.session_service import SessionService

    svc = SessionService()
    svc.add_to_working_memory("u1", "user", "first")
    svc.add_to_working_memory("u1", "assistant", "reply")

    restarted = SessionService()

    assert restarted.get_working_memory("u1", limit=1) == [
        {"user": "first", "assistant": "reply", "ts": restarted.get_working_memory("u1", limit=1)[0]["ts"]}
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_session_service.py -q
```

Expected: FAIL because `agentmind.services.session_service` does not exist.

- [ ] **Step 3: Implement minimal SessionService**

Create `src/agentmind/services/session_service.py` with:

```python
"""SessionService — persistent session and working-memory state."""

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone


def _now_sqlite() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class SessionService:
    """Persist active session, force-new flag, and recent working memory."""

    _working_memory_max = 20

    def __init__(self, store=None):
        if store is None:
            from agentmind.memory.sqlite_store import SqliteMemoryStore
            store = SqliteMemoryStore()
        self._store = store
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        return self._store._get_conn()

    def _ensure_schema(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    user_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    force_new_next INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS working_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_working_memory_user_id ON working_memory(user_id, id)"
            )
            conn.commit()
        finally:
            conn.close()

    async def new_session(self, user_id: str) -> str:
        if not user_id:
            return ""
        return await asyncio.to_thread(self._new_session_sync, user_id)

    def _new_session_sync(self, user_id: str) -> str:
        conn = self._get_conn()
        try:
            self._close_active_conversation(conn, user_id)
            sid = f"sess-{uuid.uuid4().hex[:8]}"
            now = _now_sqlite()
            conn.execute(
                """INSERT INTO session_state(user_id, session_id, force_new_next, updated_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     session_id=excluded.session_id,
                     force_new_next=1,
                     updated_at=excluded.updated_at""",
                (user_id, sid, now),
            )
            conn.execute("DELETE FROM working_memory WHERE user_id=?", (user_id,))
            conn.commit()
            return sid
        finally:
            conn.close()

    def _close_active_conversation(self, conn, user_id: str):
        row = conn.execute(
            """SELECT conversation_id FROM conversations
               WHERE user_id=? AND status='active'
               ORDER BY last_message_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        if row:
            from agentmind.memory.components.conversation_merger import ConversationMerger
            ConversationMerger().close_conversation(conn, row["conversation_id"])

    def get_active_session(self, user_id: str) -> str | None:
        if not user_id:
            return None
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT session_id FROM session_state WHERE user_id=?",
                (user_id,),
            ).fetchone()
            return row["session_id"] if row else None
        finally:
            conn.close()

    def ensure_active_session(self, user_id: str) -> tuple[str, bool]:
        if not user_id:
            return "", False
        current = self.get_active_session(user_id)
        if current:
            return current, False
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO session_state
                   (user_id, session_id, force_new_next, updated_at)
                   VALUES (?, ?, 0, ?)""",
                (user_id, sid, _now_sqlite()),
            )
            conn.commit()
            return sid, True
        finally:
            conn.close()

    def consume_force_new(self, user_id: str) -> bool:
        if not user_id:
            return False
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT force_new_next FROM session_state WHERE user_id=?",
                (user_id,),
            ).fetchone()
            value = bool(row and row["force_new_next"])
            if value:
                conn.execute(
                    "UPDATE session_state SET force_new_next=0, updated_at=? WHERE user_id=?",
                    (_now_sqlite(), user_id),
                )
                conn.commit()
            return value
        finally:
            conn.close()

    def add_to_working_memory(self, user_id: str, role: str, content: str):
        if not user_id or not content:
            return
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO working_memory(user_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (user_id, role, (content or "")[:500], _now_sqlite()),
            )
            rows = conn.execute(
                """SELECT id FROM working_memory
                   WHERE user_id=? ORDER BY id DESC LIMIT -1 OFFSET ?""",
                (user_id, self._working_memory_max),
            ).fetchall()
            if rows:
                old_ids = [r["id"] for r in rows]
                placeholders = ",".join("?" for _ in old_ids)
                conn.execute(f"DELETE FROM working_memory WHERE id IN ({placeholders})", old_ids)
            conn.commit()
        finally:
            conn.close()

    def clear_working_memory(self, user_id: str):
        if not user_id:
            return
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM working_memory WHERE user_id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()

    def get_working_memory(self, user_id: str, limit: int = 3) -> list[dict]:
        if not user_id:
            return []
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT role, content, ts FROM working_memory
                   WHERE user_id=? ORDER BY id ASC""",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        entries = [dict(r) for r in rows]
        rounds = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            if entry["role"] == "user":
                nxt = entries[i + 1] if i + 1 < len(entries) else None
                assistant = nxt["content"] if nxt and nxt["role"] == "assistant" else ""
                rounds.append({"user": entry["content"], "assistant": assistant, "ts": entry["ts"]})
                i += 2 if nxt and nxt["role"] == "assistant" else 1
            else:
                i += 1
        return rounds[-limit:] if len(rounds) > limit else rounds
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_session_service.py -q
```

Expected: PASS.

---

### Task 2: Make MemoryService delegate session state

**Files:**

- Modify: `tests/test_session_service.py`
- Modify: `src/agentmind/memory/service.py`

- [ ] **Step 1: Add failing tests for MemoryService delegation**

Append to `tests/test_session_service.py`:

```python
@pytest.mark.asyncio
async def test_memory_service_uses_session_service_force_new_flag(monkeypatch):
    from agentmind.memory import service as memory_service

    calls = []

    class FakeSessionService:
        def consume_force_new(self, user_id):
            calls.append(("consume", user_id))
            return True

        def ensure_active_session(self, user_id):
            calls.append(("ensure", user_id))
            return "sess-existing", False

    class FakeWritePipeline:
        def __init__(self, store):
            pass

        async def execute(self, mem, force_new_conversation=False):
            calls.append(("force", force_new_conversation))
            return [mem.memory_id]

    monkeypatch.setattr(memory_service, "SessionService", FakeSessionService)
    monkeypatch.setattr(
        "agentmind.memory.pipeline.write_pipeline.WritePipeline",
        FakeWritePipeline,
    )

    svc = memory_service.MemoryService(store=object())
    assert await svc.write_memory({"memory_id": "m1", "content": "hello", "user_id": "u1"}) == 1
    assert ("consume", "u1") in calls
    assert ("force", True) in calls


def test_memory_service_working_memory_delegates_to_session_service(monkeypatch):
    from agentmind.memory import service as memory_service

    calls = []

    class FakeSessionService:
        def add_to_working_memory(self, user_id, role, content):
            calls.append(("add", user_id, role, content))

        def get_working_memory(self, user_id, limit=3):
            calls.append(("get", user_id, limit))
            return [{"user": "hello", "assistant": "world", "ts": "now"}]

    monkeypatch.setattr(memory_service, "SessionService", FakeSessionService)

    svc = memory_service.MemoryService(store=object())
    svc.add_to_working_memory("u1", "user", "hello")
    assert svc.get_working_memory("u1", limit=1) == [
        {"user": "hello", "assistant": "world", "ts": "now"}
    ]
    assert ("add", "u1", "user", "hello") in calls
    assert ("get", "u1", 1) in calls
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_session_service.py::test_memory_service_uses_session_service_force_new_flag tests/test_session_service.py::test_memory_service_working_memory_delegates_to_session_service -q
```

Expected: FAIL because `memory/service.py` does not expose module-level `SessionService` and still uses class-level dictionaries.

- [ ] **Step 3: Implement minimal MemoryService delegation**

Modify `src/agentmind/memory/service.py`:

```python
from agentmind.services.session_service import SessionService
```

Remove the class-level session dictionaries. In `write_memory()`:

```python
session = SessionService(self._store)
force_new = False
if mem.user_id:
    if session.consume_force_new(mem.user_id):
        force_new = True
    elif mem.memory_type == MemoryType.EPISODIC:
        _, created = session.ensure_active_session(mem.user_id)
        force_new = created
```

In `new_session()`, delegate:

```python
return await SessionService(self._store).new_session(user_id)
```

In `get_active_session()`, `_clear_working_memory()`, `add_to_working_memory()`, and `get_working_memory()`, delegate to `SessionService(self._store)`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_session_service.py -q
```

Expected: PASS.

---

### Task 3: Package verification

**Files:**

- Modify only the files listed above

- [ ] **Step 1: Run focused and related verification**

Run:

```bash
pytest tests/test_session_service.py -q
pytest tests/test_session_service.py tests/test_memory_service_convergence.py tests/test_memory.py tests/test_memory_retrieval_eval.py -q
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

- Spec coverage: Covers Phase 2 package 2 only: MemoryService process-local session state and working memory persistence.
- Intentional gaps: discussion state, attach binding persistence, TraceService, conflict detection, AuditService, and panel session migration are deferred.
- Placeholder scan: No placeholder tasks remain.
- Type consistency: `MemoryService` retains existing public method signatures and uses `SessionService` internally.
