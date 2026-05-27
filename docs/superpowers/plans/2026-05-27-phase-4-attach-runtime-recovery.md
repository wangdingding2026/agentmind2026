# Phase 4 Attach Runtime Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and recover attach session bindings behind `SessionRuntimeService` without moving attach runtime details into panel, API handlers, or channel adapters.

**Architecture:** `AttachRegistry` remains the in-process runtime primitive used by routing to resolve `session_id -> trace_id`. `SessionRuntimeStore` gains a small SQLite table for attach bindings, and `AttachRegistry` mirrors bind/unbind changes into that store. `SessionRuntimeService.restore_runtime_state()` restores both active discussions and attach bindings into the injected/default registries during startup.

**Tech Stack:** Python, SQLite, `AttachRegistry`, `SessionRuntimeStore`, `SessionRuntimeService`, pytest, pytest-asyncio.

---

## Scope

Target in this package:

- Extend `SessionRuntimeStore` with attach binding persistence:
  - `upsert_attach_binding(session_id, trace_id)`;
  - `delete_attach_binding(trace_id)`;
  - `list_attach_bindings()`.
- Add optional `runtime_store` support to `AttachRegistry`.
- Mirror `AttachRegistry.bind(session_id, trace_id)` into the runtime store.
- Mirror `AttachRegistry.unbind(trace_id)` into the runtime store.
- Add `AttachRegistry.restore_bindings(bindings)` so recovery does not mutate private dicts externally.
- Update `SessionRuntimeService.restore_runtime_state()` to restore both discussions and attach bindings.
- Update startup so `app.state.attach_registry` is created before runtime restore and passed into `SessionRuntimeService`.
- Keep routing behavior unchanged: `RoutingService` may continue reading `app.state.attach_registry` as the runtime primitive.
- Update Phase 3 boundary docs to say attach binding state has startup recovery support, while stream listener queues remain volatile.

Out of scope:

- Do not persist stream listener queues or stream backlog.
- Do not change attached-command routing behavior.
- Do not move routing attach interception out of `RoutingService`.
- Do not change task history persistence.
- Do not change ChannelHub or Feishu behavior.
- Do not start Phase 5 CPE or AgentShield work.

## Files

- Modify: `src/agentmind/services/session_runtime_store.py`
  - Add attach binding schema and CRUD.
- Modify: `src/agentmind/api/attach_registry.py`
  - Add optional runtime store, store mirroring, and restore method.
- Modify: `src/agentmind/services/session_runtime_service.py`
  - Restore attach bindings in addition to active discussions.
- Modify: `src/agentmind/startup.py`
  - Create `app.state.attach_registry` before lifespan restore and pass it to `SessionRuntimeService`.
- Modify: `tests/test_session_runtime_store.py`
  - Add RED/GREEN coverage for attach binding persistence and dynamic data-dir behavior.
- Modify: `tests/test_attach.py`
  - Add RED/GREEN coverage for registry store mirroring and restore.
- Modify: `tests/test_session_runtime_service.py`
  - Add RED/GREEN coverage for service restoring attach bindings.
- Modify: `tests/test_startup.py`
  - Update startup restore test to assert the app attach registry is passed to the service.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Update runtime boundary note and next migration direction.
- Modify: `docs/phase3/phase-3-closure-status.md`
  - Record this Phase 4 package and next migration direction.

## Tasks

### Task 1: RED Store Persists Attach Bindings

**Files:**
- Modify: `tests/test_session_runtime_store.py`

- [ ] **Step 1: Add failing attach store tests**

Add:

```python
def test_session_runtime_store_persists_attach_bindings(tmp_path):
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    store = SessionRuntimeStore(tmp_path / "runtime.db")

    store.upsert_attach_binding("s1", "t1")
    assert store.list_attach_bindings() == {"s1": "t1"}

    store.upsert_attach_binding("s1", "t2")
    assert store.list_attach_bindings() == {"s1": "t2"}

    store.delete_attach_binding("t2")
    assert store.list_attach_bindings() == {}
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_store.py::test_session_runtime_store_persists_attach_bindings -q
```

Expected: FAIL because `SessionRuntimeStore` has no attach binding methods.

### Task 2: GREEN Store Attach Binding CRUD

**Files:**
- Modify: `src/agentmind/services/session_runtime_store.py`

- [ ] **Step 1: Add attach schema**

Extend `_ensure_schema()`:

```python
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attach_bindings (
                session_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL UNIQUE,
                updated_at TEXT NOT NULL
            )
        """)
```

- [ ] **Step 2: Add attach CRUD methods**

Add:

```python
    def upsert_attach_binding(self, session_id: str, trace_id: str):
        self._ensure_schema()
        conn = self._connect()
        conn.execute("DELETE FROM attach_bindings WHERE trace_id=?", (trace_id,))
        conn.execute(
            """
            INSERT INTO attach_bindings (session_id, trace_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                trace_id=excluded.trace_id,
                updated_at=excluded.updated_at
            """,
            (session_id, trace_id, storage_db.now_iso()),
        )
        conn.commit()
        conn.close()

    def delete_attach_binding(self, trace_id: str):
        self._ensure_schema()
        conn = self._connect()
        conn.execute("DELETE FROM attach_bindings WHERE trace_id=?", (trace_id,))
        conn.commit()
        conn.close()

    def list_attach_bindings(self) -> dict[str, str]:
        self._ensure_schema()
        conn = self._connect()
        rows = conn.execute(
            "SELECT session_id, trace_id FROM attach_bindings ORDER BY session_id"
        ).fetchall()
        conn.close()
        return {row["session_id"]: row["trace_id"] for row in rows}
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_store.py::test_session_runtime_store_persists_attach_bindings -q
```

Expected: 1 passed.

### Task 3: RED AttachRegistry Mirrors Store

**Files:**
- Modify: `tests/test_attach.py`

- [ ] **Step 1: Add failing mirror test**

Add under `TestAttachRegistry`:

```python
    def test_attach_registry_persists_binding_lifecycle_to_runtime_store(self):
        from agentmind.api.attach_registry import AttachRegistry

        class Store:
            def __init__(self):
                self.upserts = []
                self.deletes = []

            def upsert_attach_binding(self, session_id, trace_id):
                self.upserts.append((session_id, trace_id))

            def delete_attach_binding(self, trace_id):
                self.deletes.append(trace_id)

        store = Store()
        reg = AttachRegistry(runtime_store=store)

        reg.bind("s1", "t1")
        reg.unbind("t1")

        assert store.upserts == [("s1", "t1")]
        assert store.deletes == ["t1"]
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_attach.py::TestAttachRegistry::test_attach_registry_persists_binding_lifecycle_to_runtime_store -q
```

Expected: FAIL because `AttachRegistry.__init__()` does not accept `runtime_store`.

### Task 4: GREEN AttachRegistry Store Mirroring

**Files:**
- Modify: `src/agentmind/api/attach_registry.py`

- [ ] **Step 1: Add optional runtime store and mirror methods**

Update `AttachRegistry`:

```python
class AttachRegistry:
    def __init__(self, runtime_store=None):
        self._attachments: dict[str, str] = {}
        self._task_owners: dict[str, str] = {}
        self._runtime_store = runtime_store

    def bind(self, session_id: str, trace_id: str):
        old_trace_id = self._attachments.get(session_id)
        if old_trace_id:
            self._task_owners.pop(old_trace_id, None)
        self._attachments[session_id] = trace_id
        self._task_owners[trace_id] = session_id
        if self._runtime_store is not None:
            self._runtime_store.upsert_attach_binding(session_id, trace_id)

    def unbind(self, trace_id: str):
        session_id = self._task_owners.pop(trace_id, None)
        if session_id:
            self._attachments.pop(session_id, None)
            if self._runtime_store is not None:
                self._runtime_store.delete_attach_binding(trace_id)
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_attach.py::TestAttachRegistry::test_attach_registry_persists_binding_lifecycle_to_runtime_store -q
```

Expected: 1 passed.

### Task 5: RED AttachRegistry Restores Bindings

**Files:**
- Modify: `tests/test_attach.py`

- [ ] **Step 1: Add failing restore test**

Add:

```python
    def test_attach_registry_restores_bindings_without_store_writes(self):
        from agentmind.api.attach_registry import AttachRegistry

        class Store:
            def __init__(self):
                self.upserts = []

            def upsert_attach_binding(self, session_id, trace_id):
                self.upserts.append((session_id, trace_id))

        store = Store()
        reg = AttachRegistry(runtime_store=store)

        reg.restore_bindings({"s1": "t1", "s2": "t2"})

        assert reg.get_bound_task("s1") == "t1"
        assert reg.get_bound_task("s2") == "t2"
        assert store.upserts == []
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_attach.py::TestAttachRegistry::test_attach_registry_restores_bindings_without_store_writes -q
```

Expected: FAIL because `AttachRegistry` has no `restore_bindings()`.

### Task 6: GREEN AttachRegistry Restore

**Files:**
- Modify: `src/agentmind/api/attach_registry.py`

- [ ] **Step 1: Add restore method**

Add:

```python
    def restore_bindings(self, bindings: dict[str, str]):
        self._attachments = {
            str(session_id): str(trace_id)
            for session_id, trace_id in bindings.items()
        }
        self._task_owners = {
            trace_id: session_id
            for session_id, trace_id in self._attachments.items()
        }
```

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_attach.py::TestAttachRegistry::test_attach_registry_restores_bindings_without_store_writes -q
```

Expected: 1 passed.

### Task 7: RED SessionRuntimeService Restores Attach Bindings

**Files:**
- Modify: `tests/test_session_runtime_service.py`

- [ ] **Step 1: Add failing service restore test**

Add:

```python
def test_session_runtime_service_restores_persisted_attach_bindings():
    from agentmind.services.session_runtime_service import SessionRuntimeService

    class Registry:
        def restore_discussions(self, discussions):
            pass

    class AttachRegistry:
        def __init__(self):
            self.restored = None

        def restore_bindings(self, bindings):
            self.restored = bindings

    class Store:
        def list_discussions(self):
            return {}

        def list_attach_bindings(self):
            return {"s1": "t1", "s2": "t2"}

    attach_registry = AttachRegistry()
    result = SessionRuntimeService(
        session_registry=Registry(),
        task_service=_TaskService(),
        attach_registry=attach_registry,
        runtime_store=Store(),
    ).restore_runtime_state()

    assert result == {"restored_discussions": 0, "restored_attach_bindings": 2}
    assert attach_registry.restored == {"s1": "t1", "s2": "t2"}
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_restores_persisted_attach_bindings -q
```

Expected: FAIL because `restore_runtime_state()` does not call `list_attach_bindings()` or `restore_bindings()`.

### Task 8: GREEN SessionRuntimeService Restore Attach

**Files:**
- Modify: `src/agentmind/services/session_runtime_service.py`
- Modify: `tests/test_session_runtime_service.py`

- [ ] **Step 1: Update existing discussion restore expectation**

Change `test_session_runtime_service_restores_persisted_discussions()` expected result to:

```python
assert result == {"restored_discussions": 2, "restored_attach_bindings": 0}
```

Add `list_attach_bindings()` to that test `Store`:

```python
        def list_attach_bindings(self):
            return {}
```

- [ ] **Step 2: Restore attach bindings**

Update `restore_runtime_state()`:

```python
    def restore_runtime_state(self):
        discussions = self.runtime_store.list_discussions()
        self.session_registry.restore_discussions(discussions)
        attach_bindings = self.runtime_store.list_attach_bindings()
        if self.attach_registry is not None:
            self.attach_registry.restore_bindings(attach_bindings)
        return {
            "restored_discussions": len(discussions),
            "restored_attach_bindings": len(attach_bindings),
        }
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_service.py::test_session_runtime_service_restores_persisted_discussions tests/test_session_runtime_service.py::test_session_runtime_service_restores_persisted_attach_bindings -q
```

Expected: 2 passed.

### Task 9: RED Startup Passes App Attach Registry To Restore

**Files:**
- Modify: `tests/test_startup.py`

- [ ] **Step 1: Update startup restore test expectation**

Change `test_startup_restores_session_runtime_state()` fake:

```python
    class FakeSessionRuntimeService:
        def __init__(self, **kwargs):
            calls.append(("service", kwargs))

        def restore_runtime_state(self):
            calls.append("restore")
            return {"restored_discussions": 1, "restored_attach_bindings": 1}
```

Change final assertion:

```python
    service_call = next(call for call in calls if isinstance(call, tuple) and call[0] == "service")
    assert service_call[1]["attach_registry"] is app.state.attach_registry
    assert "restore" in calls
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_startup.py::test_startup_restores_session_runtime_state -q
```

Expected: FAIL because startup calls `SessionRuntimeService()` without the app attach registry.

### Task 10: GREEN Startup Restore Uses App Attach Registry

**Files:**
- Modify: `src/agentmind/startup.py`

- [ ] **Step 1: Move attach registry creation before lifespan restore**

Create `attach_registry` before the lifespan function:

```python
        attach_registry = __import__(
            "agentmind.api.attach_registry", fromlist=["AttachRegistry"]
        ).AttachRegistry()
```

Set app state later with that object:

```python
        app.state.attach_registry = attach_registry
```

- [ ] **Step 2: Pass attach registry into runtime restore**

In lifespan:

```python
            SessionRuntimeService(attach_registry=attach_registry).restore_runtime_state()
```

- [ ] **Step 3: Run GREEN**

Run:

```bash
pytest tests/test_startup.py::test_startup_restores_session_runtime_state -q
```

Expected: 1 passed.

### Task 11: RED Runtime Store Default Data Dir Covers Attach

**Files:**
- Modify: `tests/test_session_runtime_store.py`

- [ ] **Step 1: Add dynamic data-dir attach assertion**

Extend `test_default_session_runtime_store_uses_current_data_dir()`:

```python
    store.upsert_attach_binding("s1", "t1")
    assert store.list_attach_bindings() == {"s1": "t1"}
```

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/test_session_runtime_store.py::test_default_session_runtime_store_uses_current_data_dir -q
```

Expected: FAIL until attach CRUD uses the same lazy `storage_db.DATA_DIR` path.

### Task 12: GREEN Dynamic Data Dir For Attach

**Files:**
- Modify: `src/agentmind/services/session_runtime_store.py`

- [ ] **Step 1: Confirm attach CRUD uses `_connect()` and `storage_db.now_iso()`**

The Task 2 implementation already uses `_connect()` and `storage_db.now_iso()`. If the RED test still fails, update attach methods to use the same path and timestamp pattern as discussion methods.

- [ ] **Step 2: Run GREEN**

Run:

```bash
pytest tests/test_session_runtime_store.py::test_default_session_runtime_store_uses_current_data_dir -q
```

Expected: 1 passed.

### Task 13: Documentation Update

**Files:**
- Modify: `docs/phase3/panel-control-plane-boundary.md`
- Modify: `docs/phase3/phase-3-closure-status.md`

- [ ] **Step 1: Update panel boundary note**

Replace:

```markdown
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state has startup recovery support, while stream listener queues remain volatile live runtime state for a later package.
```

with:

```markdown
- `active_sessions`, `attach_to_task`, and `panel_task_stream` now delegate to `SessionRuntimeService`; active discussion state and attach bindings have startup recovery support, while stream listener queues remain volatile live runtime state for a later package.
```

- [ ] **Step 2: Update next migration direction**

Replace the next direction list with:

```markdown
1. Stream resumability design that does not try to persist live queue objects.
2. Remaining channel runtime concerns behind service/channel boundaries.
```

- [ ] **Step 3: Update Phase 3 closure status**

In Phase 4 completed package list, add:

```markdown
9. Added startup recovery for persisted attach bindings behind `SessionRuntimeService`.
```

Replace the next-step paragraph with:

```markdown
Next, continue reducing runtime-only state behind service/channel boundaries. The preferred next package is a stream resumability design that does not try to persist live queue objects, followed by remaining ChannelHub compatibility cleanup.
```

### Task 14: Strict Verification And Commit

**Files:**
- All modified files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_session_runtime_store.py tests/test_attach.py::TestAttachRegistry tests/test_session_runtime_service.py tests/test_startup.py::test_startup_restores_session_runtime_state -q
```

Expected: pass.

- [ ] **Step 2: Run attach/session/startup regression**

Run:

```bash
pytest tests/test_attach.py tests/test_session_runtime_service.py tests/test_startup.py tests/test_router.py -q
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
git add src/agentmind/services/session_runtime_store.py src/agentmind/services/session_runtime_service.py src/agentmind/api/attach_registry.py src/agentmind/startup.py tests/test_session_runtime_store.py tests/test_session_runtime_service.py tests/test_attach.py tests/test_startup.py docs/phase3/panel-control-plane-boundary.md docs/phase3/phase-3-closure-status.md docs/superpowers/plans/2026-05-27-phase-4-attach-runtime-recovery.md
git commit -m "refactor: recover attach runtime bindings"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: Covers attach binding persistence/recovery only. It explicitly excludes stream persistence, task history changes, routing attach behavior changes, ChannelHub changes, and Phase 5 work.
- Placeholder scan: No TODO/TBD placeholders are present.
- Type consistency: Uses existing `AttachRegistry`, `SessionRuntimeStore`, `SessionRuntimeService`, `storage_db`, and pytest names.
- Architecture fit: Keeps panel/API as adapters, keeps routing on the runtime registry primitive, and puts persistence/recovery behind service/runtime boundaries.
