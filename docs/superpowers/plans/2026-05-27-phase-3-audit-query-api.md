# AgentMind Phase 3 Audit Query API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose AuditService events through a panel API for control-plane explanation workflows.

**Architecture:** `AuditService` remains the only audit query boundary. The panel router adds a thin `GET /panel/api/audit/events` adapter that passes query parameters to `AuditService.query_events()` and returns `{ "events": [...] }`. This package does not modify the static panel UI.

**Tech Stack:** Python 3.12, FastAPI APIRouter, SQLite-backed AuditService, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- `AuditService`
  - Owns audit event persistence and filtering.
  - Supports querying by `module`, `action`, `agent_id`, `risk_level`, `trace_id`, and `actor`.
- `panel/server.py`
  - Exposes a thin service adapter endpoint.
  - Does not read audit SQLite directly.
- Future control console
  - Can build explanation views from this endpoint plus existing trace/task endpoints.

Transition compatibility:

- No front-end/static UI changes in this package.
- Existing panel APIs and response shapes remain unchanged.
- Endpoint defaults to a bounded limit.

Not allowed:

- SQL queries in panel endpoints.
- Duplicating AuditService filtering logic in panel.
- Adding long-term compatibility around old non-service paths.
- Touching deleted files.

Out of scope:

- Audit log front-end page.
- Correlated request explanation view.
- Configurable retention/export.
- Auth actor extraction.

## Files

Create:

- `docs/superpowers/plans/2026-05-27-phase-3-audit-query-api.md`

Modify:

- `src/agentmind/panel/server.py`
- `tests/test_audit_service.py`
- `tests/test_panel_api.py`

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
pytest tests/test_panel_api.py::TestPanelAPI::test_audit_events_endpoint_uses_audit_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: AuditService Query Filter Coverage

**Files:**

- Modify: `tests/test_audit_service.py`

- [x] **Step 1: Write RED or strengthening test**

Add coverage that `query_events(action=..., limit=...)` filters by action and respects limit.

- [x] **Step 2: Verify focused test**

Run:

```bash
pytest tests/test_audit_service.py -q
```

Expected: PASS if current service already supports this; otherwise FAIL and implement only the missing service behavior.

---

### Task 2: Panel Audit Events Endpoint

**Files:**

- Modify: `tests/test_panel_api.py`
- Modify: `src/agentmind/panel/server.py`

- [x] **Step 1: Write RED panel endpoint test**

Add `TestPanelAPI::test_audit_events_endpoint_uses_audit_service` that monkeypatches `agentmind.panel.server.AuditService`, calls:

```text
GET /panel/api/audit/events?module=config&action=update&agent_id=a1&risk_level=medium&trace_id=t1&actor=system&limit=7
```

and asserts:

- Status is 200.
- Response is `{ "events": [...] }`.
- `AuditService.query_events()` received all filters.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_audit_events_endpoint_uses_audit_service -q
```

Expected: FAIL with 404 because endpoint does not exist.

- [x] **Step 3: Implement thin endpoint**

In `panel/server.py`:

- Import `AuditService`.
- Add `@router.get("/audit/events")`.
- Pass query parameters directly to `AuditService().query_events(...)`.
- Return `{"events": events}`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_audit_events_endpoint_uses_audit_service -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_audit_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_audit_events_endpoint_uses_audit_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-audit-query-api.md tests/test_audit_service.py tests/test_panel_api.py src/agentmind/panel/server.py
git commit -m "feat: expose audit events api"
```
