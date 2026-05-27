# Phase 4 Session Discussion Runtime Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and recover active discussion runtime state behind `SessionRuntimeService` without moving session logic back into panel, API, or channel adapters.

**Architecture:** `SessionRegistry` remains the in-process runtime primitive for discussion and stream state, but active discussion state is mirrored to a small SQLite-backed service store. `SessionRuntimeService` owns the recovery boundary by restoring persisted discussions into the registry during startup and by exposing recovered sessions to the panel. Stream listeners remain volatile live queues in this package and are explicitly not persisted or restored.

**Tech Stack:** Python, SQLite, `SessionRegistry`, `SessionRuntimeService`, pytest, pytest-asyncio.

---

## Scope

Target in this package:

- Add a small SQLite-backed runtime store for discussion state.
- Persist discussion lifecycle transitions:
  - `start_discussion(user_id)` stores `stop=False`.
  - `stop_discussion(user_id)` stores `stop=True` only if the discussion exists.
  - `end_discussion(user_id)` removes the persisted row.
- Add a `SessionRegistry.restore_discussions()` method so recovered state can be loaded without exposing private dict mutation to callers.
- Add `SessionRuntimeService.restore_runtime_state()` that reads active discussion rows and restores them into the injected/default registry.
- Call `SessionRuntimeService().restore_runtime_state()` from startup lifespan before background tasks and channel startup.
- Keep stream listener queues and stream backlog in memory only. This package must not persist `_streams`, queue objects, or stream listeners.
- Update Phase 3 boundary docs to say discussion runtime state now has recovery support while stream listener queues remain an explicit future package.

Out of scope:

- Do not persist stream listener queues or stream backlog.
- Do not persist attach bindings.
- Do not change discussion routing behavior in `api/router.py` or `RoutingService`.
- Do not change Feishu stop-word handling.
- Do not move ChannelHub into `SessionRuntimeService`.
- Do not start Phase 5 CPE or AgentShield work.

## Files

- Create: `src/agentmind/services/session_runtime_store.py`
  - Owns SQLite schema and CRUD for active discussion rows.
- Modify: `src/agentmind/routing/side_effects/session_registry.py`
  - Accepts an optional runtime store.
  - Mirrors discussion lifecycle changes to the store.
  - Adds `restore_discussions(discussions)`.
- Modify: `src/agentmind/services/session_runtime_service.py`
  - Accepts an optional runtime store.
  - Adds `restore_runtime_state()`.
- Modify: `src/agentmind/startup.py`
  - Calls `SessionRuntimeService().restore_runtime_state()` during lifespan startup.
- Modify: `tests/test_session_runtime_store.py`
  - Adds RED/GREEN coverage for persistence CRUD.
- Modify: `tests/test_session_runtime_service.py`
  - Adds RED/GREEN coverage for service recovery and stream volatility.
- Modify: `tests/test_stream.py`
  - Adds focused coverage that stream state remains in-memory only.
- Modify: `tests/test_startup.py`
  - Adds RED/GREEN coverage that startup delegates runtime restore to `SessionRuntimeService`.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Records that active discussion state now has recovery support and stream listeners remain volatile.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Records the Phase 4 package completion and next migration direction.

## Tasks

### Task 1: RED Runtime Store Persists Discussion State

**Files:**
- Create: `tests/test_session_runtime_store.py`

- [ ] **Step 1: Add failing runtime store tests**

Create `tests/test_session_runtime_store.py`:

```python
def test_session_runtime_store_persists_discussion_lifecycle(tmp_path):
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    db_path = tmp_path / "runtime.db"
    store = SessionRuntimeStore(db_path)

    store.upsert_discussion("u1", stop=False)
    assert store.list_discussions() == {"u1": {"stop": False}}

    store.upsert_discussion("u1", stop=True)
    assert store.list_discussions() == {"u1": {"stop": True}}

    store.delete_discussion("u1")
    assert store.list_discussions() == {}


def test_session_runtime_store_initializes_schema_for_new_database(tmp_path):
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    db_path = tmp_path / "nested" / "runtime.db"
    store = SessionRuntimeStore(db_path)

    assert store.list_discussions() == {}
    assert db_path.exists()
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_store.py -q
```

Expected: FAIL because `agentmind.services.session_runtime_store` does not exist.

### Task 2: GREEN Runtime Store

**Files:**
- Create: `src/agentmind/services/session_runtime_store.py`

- [ ] **Step 1: Implement minimal SQLite store**

Create `src/agentmind/services/session_runtime_store.py`:

```python
import sqlite3
from pathlib import Path

from agentmind.storage.db import DATA_DIR, now_iso


class SessionRuntimeStore:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path is not None else DATA_DIR / "runtime_state.db"
        self._ensure_schema()

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_discussions (
                user_id TEXT PRIMARY KEY,
                stop INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def upsert_discussion(self, user_id: str, stop: bool):
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO active_discussions (user_id, stop, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stop=excluded.stop,
                updated_at=excluded.updated_at
            """,
            (user_id, int(stop), now_iso()),
        )
        conn.commit()
        conn.close()

    def delete_discussion(self, user_id: str):
        conn = self._connect()
        conn.execute("DELETE FROM active_discussions WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

    def list_discussions(self) -> dict[str, dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT user_id, stop FROM active_discussions ORDER BY user_id"
        ).fetchall()
        conn.close()
        return {row["user_id"]: {"stop": bool(row["stop"])} for row in rows}
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_store.py -q
```

Expected: 2 passed.

### Task 3: RED SessionRegistry Mirrors Discussions To Store

**Files:**
- Modify: `tests/test_session_runtime_service.py`

- [ ] **Step 1: Add fake store and failing registry mirror test**

Add this test to `tests/test_session_runtime_service.py`:

```python
def test_session_registry_persists_discussion_lifecycle_to_runtime_store():
    from agentmind.routing.side_effects.session_registry import SessionRegistry

    class Store:
        def __init__(self):
            self.upserts = []
            self.deletes = []

        def upsert_discussion(self, user_id, stop):
            self.upserts.append((user_id, stop))

        def delete_discussion(self, user_id):
            self.deletes.append(user_id)

    store = Store()
    registry = SessionRegistry(runtime_store=store)

    registry.start_discussion("u1")
    registry.stop_discussion("u1")
    registry.end_discussion("u1")

    assert store.upserts == [("u1", False), ("u1", True)]
    assert store.deletes == ["u1"]
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_registry_persists_discussion_lifecycle_to_runtime_store -q
```

Expected: FAIL because `SessionRegistry.__init__()` does not accept `runtime_store`.

### Task 4: GREEN SessionRegistry Store Mirroring

**Files:**
- Modify: `src/agentmind/routing/side_effects/session_registry.py`

- [ ] **Step 1: Add optional runtime store and mirror writes**

Change constructor and discussion methods:

```python
    def __init__(self, runtime_store=None):
        self._streams: dict[str, dict] = {}
        self._discussions: dict[str, dict] = {}
        self._runtime_store = runtime_store
```

Update discussion methods:

```python
    def start_discussion(self, user_id: str):
        self._discussions[user_id] = {"stop": False}
        if self._runtime_store is not None:
            self._runtime_store.upsert_discussion(user_id, stop=False)

    def stop_discussion(self, user_id: str):
        disc = self._discussions.get(user_id)
        if disc:
            disc["stop"] = True
            if self._runtime_store is not None:
                self._runtime_store.upsert_discussion(user_id, stop=True)

    def end_discussion(self, user_id: str):
        self._discussions.pop(user_id, None)
        if self._runtime_store is not None:
            self._runtime_store.delete_discussion(user_id)
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_registry_persists_discussion_lifecycle_to_runtime_store -q
```

Expected: 1 passed.

### Task 5: RED SessionRuntimeService Restores Discussions

**Files:**
- Modify: `tests/test_session_runtime_service.py`

- [ ] **Step 1: Add failing restore test**

Add this test:

```python
def test_session_runtime_service_restores_persisted_discussions():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    class Registry:
        def __init__(self):
            self.restored = None

        def restore_discussions(self, discussions):
            self.restored = discussions

    class Store:
        def list_discussions(self):
            return {
                "u1": {"stop": False},
                "u2": {"stop": True},
            }

    registry = Registry()
    result = SessionRuntimeService(
        session_registry=registry,
        task_service=_TaskService(),
        runtime_store=Store(),
    ).restore_runtime_state()

    assert result == {"restored_discussions": 2}
    assert registry.restored == {
        "u1": {"stop": False},
        "u2": {"stop": True},
    }
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_restores_persisted_discussions -q
```

Expected: FAIL because `SessionRuntimeService.__init__()` does not accept `runtime_store`.

### Task 6: GREEN SessionRuntimeService Restore Boundary

**Files:**
- Modify: `src/agentmind/routing/side_effects/session_registry.py`
- Modify: `src/agentmind/services/session_runtime_service.py`

- [ ] **Step 1: Add registry restore method**

Add to `SessionRegistry`:

```python
    def restore_discussions(self, discussions: dict[str, dict]):
        self._discussions = {
            str(user_id): {"stop": bool(discussion.get("stop", False))}
            for user_id, discussion in discussions.items()
        }
```

- [ ] **Step 2: Add service runtime store dependency and restore method**

Update `SessionRuntimeService`:

```python
class SessionRuntimeService:
    def __init__(self, session_registry=None, task_service=None, attach_registry=None, runtime_store=None):
        self.session_registry = session_registry or self._default_session_registry()
        self.task_service = task_service or TaskService()
        self.attach_registry = attach_registry
        self.runtime_store = runtime_store or self._default_runtime_store()
```

Add:

```python
    def restore_runtime_state(self):
        discussions = self.runtime_store.list_discussions()
        self.session_registry.restore_discussions(discussions)
        return {"restored_discussions": len(discussions)}

    @staticmethod
    def _default_runtime_store():
        from agentmind.services.session_runtime_store import SessionRuntimeStore

        return SessionRuntimeStore()
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_restores_persisted_discussions -q
```

Expected: 1 passed.

### Task 7: RED Default Registry Uses Runtime Store

**Files:**
- Modify: `tests/test_session_runtime_service.py`

- [ ] **Step 1: Add failing default-registry persistence test**

Add:

```python
def test_default_session_registry_has_runtime_store():
    from agentmind.routing.side_effects.session_registry import session_registry

    assert getattr(session_registry, "_runtime_store", None) is not None
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_default_session_registry_has_runtime_store -q
```

Expected: FAIL because the module-level `session_registry` is created without a runtime store.

### Task 8: GREEN Default Registry Runtime Store

**Files:**
- Modify: `src/agentmind/routing/side_effects/session_registry.py`

- [ ] **Step 1: Create module-level registry with default store**

Replace:

```python
session_registry = SessionRegistry()
```

with:

```python
def _default_runtime_store():
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    return SessionRuntimeStore()


session_registry = SessionRegistry(runtime_store=_default_runtime_store())
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_default_session_registry_has_runtime_store -q
```

Expected: 1 passed.

### Task 9: RED Stream State Remains Volatile

**Files:**
- Modify: `tests/test_stream.py`

- [ ] **Step 1: Add focused non-persistence test**

Add this test under `TestStreamRegistry`:

```python
def test_stream_backlog_is_not_restored_with_discussions():
    from agentmind.routing.side_effects.session_registry import SessionRegistry

    sr = SessionRegistry()
    sr.broadcast_stream_chunk("tr-backlog", {"event": "partial", "data": "hello"})
    assert "tr-backlog" in sr._streams

    sr.restore_discussions({"u1": {"stop": False}})

    assert sr.list_discussions() == {"u1": {"stop": False}}
    assert sr._streams == {}
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_stream.py::TestStreamRegistry::test_stream_backlog_is_not_restored_with_discussions -q
```

Expected: FAIL because `SessionRegistry` does not yet define `restore_discussions`, or because restore does not clear volatile stream state.

### Task 10: GREEN Keep Stream State Volatile During Restore

**Files:**
- Modify: `src/agentmind/routing/side_effects/session_registry.py`

- [ ] **Step 1: Ensure restore clears in-process streams**

Update `restore_discussions()`:

```python
    def restore_discussions(self, discussions: dict[str, dict]):
        self._streams = {}
        self._discussions = {
            str(user_id): {"stop": bool(discussion.get("stop", False))}
            for user_id, discussion in discussions.items()
        }
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_stream.py::TestStreamRegistry::test_stream_backlog_is_not_restored_with_discussions -q
```

Expected: 1 passed.

### Task 11: RED Startup Restores Runtime State

**Files:**
- Modify: `tests/test_startup.py`

- [ ] **Step 1: Add failing startup delegation test**

Add:

```python
@pytest.mark.asyncio
async def test_startup_restores_session_runtime_state(monkeypatch, tmp_path):
    from agentmind.startup import AgentMindBootstrapper

    calls = []

    class FakeSessionRuntimeService:
        def restore_runtime_state(self):
            calls.append("restore")
            return {"restored_discussions": 1}

    async def no_op_health_checks(self):
        calls.append("health")

    monkeypatch.setattr("agentmind.startup.SessionRuntimeService", FakeSessionRuntimeService, raising=False)
    monkeypatch.setattr("agentmind.agents.registry.AgentRegistry.run_health_checks", no_op_health_checks)
    monkeypatch.setattr("agentmind.startup.mark_timed_out_tasks_retriable", lambda: calls.append("tasks"))
    monkeypatch.setattr("agentmind.startup._maybe_start_feishu", AsyncMock(return_value=None))

    data_home = tmp_path
    (data_home / "config").mkdir(parents=True)
    (data_home / "config" / "settings.yaml").write_text("feishu:\n  enabled: false\n", encoding="utf-8")
    (data_home / "config" / "agents.yaml").write_text("agents: []\n", encoding="utf-8")
    (data_home / "config" / "routes.yaml").write_text("rules: []\n", encoding="utf-8")

    app = AgentMindBootstrapper(port=8765, data_home=data_home).create_app()
    async with app.router.lifespan_context(app):
        pass

    assert "restore" in calls
```

Ensure `tests/test_startup.py` imports `AsyncMock` if it does not already:

```python
from unittest.mock import AsyncMock
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_startup.py::test_startup_restores_session_runtime_state -q
```

Expected: FAIL because startup does not import/call `SessionRuntimeService`.

### Task 12: GREEN Startup Restore Hook

**Files:**
- Modify: `src/agentmind/startup.py`

- [ ] **Step 1: Import service**

Add:

```python
from agentmind.services.session_runtime_service import SessionRuntimeService
```

- [ ] **Step 2: Restore runtime state in lifespan**

In lifespan, after `mark_timed_out_tasks_retriable()` and before background tasks:

```python
            SessionRuntimeService().restore_runtime_state()
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_startup.py::test_startup_restores_session_runtime_state -q
```

Expected: 1 passed.

### Task 13: Documentation Update

**Files:**
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/phase3/phase-3-closure-status.md`

- [ ] **Step 1: Update panel boundary note**

Replace:

```markdown
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; the underlying in-process runtime state still needs a later persistence/recovery package.
```

with:

```markdown
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state has startup recovery support, while stream listener queues remain volatile live runtime state for a later package.
```

- [ ] **Step 2: Update Phase 3 closure status**

In Phase 4 completed package list, add:

```markdown
8. Added startup recovery for persisted active discussion runtime state behind `SessionRuntimeService`; stream listener queues remain volatile.
```

Replace the next-step paragraph with:

```markdown
Next, continue reducing runtime-only state behind service/channel boundaries. The preferred next package is attach binding persistence/recovery through `SessionRuntimeService`, followed by a separate stream resumability design that does not try to persist live queue objects.
```

### Task 14: Strict Verification And Commit

**Files:**
- All modified files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_session_runtime_store.py tests/test_session_runtime_service.py tests/test_stream.py::TestStreamRegistry tests/test_startup.py::test_startup_restores_session_runtime_state -q
```

Expected: pass.

- [ ] **Step 2: Run session/startup/channel regression**

Run:

```bash
pytest tests/test_session_runtime_service.py tests/test_stream.py tests/test_startup.py tests/test_channel_hub.py tests/test_feishu_path.py -q
```

Expected: pass.

- [ ] **Step 3: Run panel/architecture regression**

Run:

```bash
pytest tests/test_panel_api.py tests/test_panel_control_plane_boundary.py tests/test_phase3_closure_audit.py -q
```

Expected: pass.

- [ ] **Step 4: Run router/panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: pass.

- [ ] **Step 5: Run full suite**

Run:

```bash
pytest -q
```

Expected: pass.

- [ ] **Step 6: Run diff and status checks**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` has no output. `git status --short` shows only the planned files before commit.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/agentmind/services/session_runtime_store.py src/agentmind/services/session_runtime_service.py src/agentmind/routing/side_effects/session_registry.py src/agentmind/startup.py tests/test_session_runtime_store.py tests/test_session_runtime_service.py tests/test_stream.py tests/test_startup.py docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md docs/superpowers/plans/2026-05-27-phase-4-session-discussion-runtime-recovery.md
git commit -m "refactor: recover session discussion runtime state"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: Covers active discussion runtime recovery only. It explicitly excludes stream listener queue persistence, attach persistence, routing discussion behavior changes, and ChannelHub changes.
- Placeholder scan: No TODO/TBD placeholders are present.
- Type consistency: Uses existing `SessionRegistry`, `SessionRuntimeService`, `DATA_DIR`, `now_iso`, and pytest names.
- Architecture fit: Keeps panel/API/channel as adapters and puts recovery behind the service/runtime boundary rather than adding new panel dependencies.
