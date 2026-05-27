# AgentMind Phase 3 Config Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route service-layer configuration writes through AuditService without scattering audit calls across panel endpoints.

**Architecture:** `ConfigService` remains the single service boundary for YAML configuration writes. This package adds an optional `AuditService` dependency to `ConfigService` so settings, routes, agents, and orchestrations writes produce structured `config/update` audit events. Panel endpoints that already use `ConfigService` inherit audit coverage; panel agent endpoints that still write YAML directly remain explicitly out of scope until they are migrated to `ConfigService`.

**Tech Stack:** Python 3.12, SQLite-backed AuditService, YAML ConfigService, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- `ConfigService`
  - Continues to own YAML read/write, validation, masking, and locking.
  - Emits audit events for write operations through `AuditService`.
- `AuditService`
  - Remains the only persistence boundary for audit events.
- Panel/control plane
  - Should not write audit rows directly.
  - Should keep routing writes through service boundaries.

Transition compatibility:

- Existing `ConfigService(config_dir)` constructor continues to work.
- Audit write failures must not break config writes.
- Existing panel tests that monkeypatch `ConfigService` remain valid.
- Panel agent add/tags/toggle still contain direct YAML writes; this package does not add audit patches there because the target fix is to migrate them to `ConfigService` later.

Not allowed:

- Adding one-off audit calls to each panel endpoint as a long-term pattern.
- Making `ConfigService` depend on FastAPI request objects.
- Changing YAML schema or panel response shapes.
- Restoring or touching deleted files.

Out of scope:

- Panel audit-log query endpoint.
- Migrating agent add/tags/toggle to `ConfigService`.
- Auditing memory cleanup/deletion.
- User identity extraction from auth/session.

## Files

Create:

- `docs/superpowers/plans/2026-05-27-phase-3-config-audit.md`

Modify:

- `src/agentmind/services/config_service.py`
- `tests/test_config_service.py`

Verify without modifying:

- `tests/test_panel_api.py`

Do not modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/api/router.py`
- Deleted files.

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_config_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: ConfigService Emits Audit Events For Writes

**Files:**

- Modify: `tests/test_config_service.py`
- Modify: `src/agentmind/services/config_service.py`

- [x] **Step 1: Write RED tests**

Add tests that inject a fake audit service into `ConfigService` and assert:

- `update_settings_sections()` records `module=config`, `action=update`, `actor=system`, `risk_level=medium`.
- `write_routes()` records the changed config area as `routes`.
- Audit payload is masked for sensitive values.
- Audit failures do not prevent the YAML write.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_config_service.py -q
```

Expected: FAIL because `ConfigService` does not accept or call an audit service.

- [x] **Step 3: Implement audit hook in ConfigService**

Add:

- Optional constructor arg `audit_service=None`.
- Private `_record_config_audit(area: str, data: dict)` method.
- Calls from `write_settings`, `update_settings_sections`, `write_agents`, `write_routes`, and `write_orchestrations`.
- Mask sensitive payload with existing `mask_sensitive()`.
- Catch audit exceptions.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_config_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Config Writes Inherit Service Audit Boundary

**Files:**

- Verify: `tests/test_panel_api.py`

- [x] **Step 1: Use existing focused service-boundary tests**

Use `TestPanelConfigServiceUsage` to confirm panel still interacts only through `ConfigService` for settings and rules saves. Do not add endpoint-level audit calls.

- [x] **Step 2: Verify test behavior**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
```

Expected: PASS after Task 1; if it fails, adjust only for constructor compatibility, not by adding endpoint-level audit writes.

---

## Final Verification

Run:

```bash
pytest tests/test_config_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-config-audit.md tests/test_config_service.py src/agentmind/services/config_service.py
git commit -m "feat: audit config writes"
```
