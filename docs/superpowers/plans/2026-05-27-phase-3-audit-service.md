# AgentMind Phase 3 AuditService Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first AuditService boundary for local, queryable platform audit events.

**Architecture:** `AuditService` owns an `audit_events` table in local SQLite and exposes typed write/query helpers. Existing `TaskService`, `TraceService`, and `TraceRecorder` remain in place; this package adds audit as a parallel service boundary and wires only one low-risk source, routing decisions, through the service.

**Tech Stack:** Python 3.12, SQLite, asyncio `to_thread`, dataclasses, pytest, pytest-asyncio.

---

## Architecture Constraints

Target architecture:

- `agentmind.services.audit_service.AuditService`
  - Owns local audit storage.
  - Records platform operations as structured events.
  - Queries by time order, module, agent, risk level, trace_id, and actor.
- `TraceRecorder`
  - Continues to write routing traces through `TraceService`.
  - Also records a routing audit event through `AuditService`.
- Future panel/control-plane code
  - Must call `AuditService`, not write audit rows directly.

Transition compatibility:

- Keep `TraceService` for route explanation traces.
- Keep `TaskService` for lifecycle status.
- Keep existing `record_task_*` compatibility wrappers.
- This first package does not add panel audit pages or convert all panel writes.

Not allowed:

- Adding ad hoc audit tables from router, panel, or storage helpers.
- Making `AuditService` depend on FastAPI request objects.
- Replacing `TraceService` or `TaskService` with audit records.
- Using external services for audit storage.
- Restoring deleted file `记忆和检索模块优化方案.md`.

Out of scope:

- Control panel audit log API/page.
- Full config write audit coverage.
- Sensitive memory access audit.
- AgentShield/CPE/self-evolution audit events.
- Export/retention policy.

## Files

Create:

- `src/agentmind/services/audit_service.py`
- `tests/test_audit_service.py`

Modify:

- `src/agentmind/services/__init__.py`
- `src/agentmind/routing/side_effects/trace_recorder.py`
- `tests/test_trace_service.py`

Do not modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/api/router.py`
- `src/agentmind/services/routing_service.py`
- Deleted file `记忆和检索模块优化方案.md`

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_audit_service.py -q
pytest tests/test_trace_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: AuditService Storage And Query Boundary

**Files:**

- Create: `tests/test_audit_service.py`
- Create: `src/agentmind/services/audit_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [x] **Step 1: Write RED tests**

Create `tests/test_audit_service.py` covering:

- `record_event()` persists an audit event to SQLite.
- `query_events()` returns newest events first.
- Filters work for `module`, `agent_id`, `risk_level`, `trace_id`, and `actor`.
- Payload is stored and returned as a dict.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_audit_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.audit_service'`.

- [x] **Step 3: Implement minimal AuditService**

Add:

- `AuditService(db_path: str = "")`
- `record_event(...)`
- `query_events(...)`
- `record_routing_decision(trace_id, agent_id, strategy, confidence, actor="", user_id="", risk_level="low", payload=None)`

SQLite table:

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    module TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT DEFAULT '',
    user_id TEXT DEFAULT '',
    trace_id TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    risk_level TEXT DEFAULT 'low',
    status TEXT DEFAULT 'success',
    message TEXT DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
)
```

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_audit_service.py -q
```

Expected: PASS.

---

### Task 2: Routing Decisions Write Audit Events Through TraceRecorder

**Files:**

- Modify: `src/agentmind/routing/side_effects/trace_recorder.py`
- Modify: `tests/test_trace_service.py`

- [x] **Step 1: Write RED test**

Update `tests/test_trace_service.py::test_trace_recorder_delegates_to_trace_service` to monkeypatch `AuditService` and assert `TraceRecorder.record_decision()` calls `record_routing_decision()`.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_trace_service.py::test_trace_recorder_delegates_to_trace_service -q
```

Expected: FAIL because `TraceRecorder` only delegates to `TraceService`.

- [x] **Step 3: Implement TraceRecorder audit write**

In `trace_recorder.py`:

- Import `AuditService`.
- After successful `TraceService().record_decision(...)`, call `AuditService().record_routing_decision(...)`.
- Keep audit write failure isolated so trace write does not fail.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_trace_service.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_audit_service.py -q
pytest tests/test_trace_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-audit-service.md tests/test_audit_service.py tests/test_trace_service.py src/agentmind/services/audit_service.py src/agentmind/services/__init__.py src/agentmind/routing/side_effects/trace_recorder.py
git commit -m "feat: add audit service"
```
