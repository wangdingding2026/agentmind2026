# Phase 3 Settings Status Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel settings and embedding read-side views behind a service-layer boundary.

**Architecture:** `SettingsStatusService` owns read-only control-plane views for settings, Feishu config display, and embedding status. `ConfigService` remains the YAML read boundary, embedding availability remains infrastructure detail, and panel handlers only call service methods and return their results. Feishu connect/disconnect/status remain transition runtime boundaries for Phase 4 `ChannelHub`.

**Tech Stack:** FastAPI panel router, service-layer Python class, pytest, existing `ConfigService`.

---

## Scope

Target in this package:

- Add `src/agentmind/services/settings_status_service.py`.
- Add `tests/test_settings_status_service.py`.
- Move the read-side logic for these panel handlers into service methods:
  - `feishu_get_config`
  - `get_settings`
  - `embedding_status`
- Update panel boundary audit so those handlers become service-backed.

Transition boundaries preserved:

- `feishu_connect`
- `feishu_disconnect`
- `feishu_status`
- `active_sessions`
- `attach_to_task`
- `panel_task_stream`
- `list_connectors`

Out of scope:

- Do not migrate Feishu connect/disconnect lifecycle.
- Do not create ChannelHub.
- Do not change settings write paths; `SettingsControlService` already owns saves.

## Files

- Create: `src/agentmind/services/settings_status_service.py`
  - Provides `get_settings_view()`, `get_feishu_config_view()`, and `get_embedding_status()`.
- Create: `tests/test_settings_status_service.py`
  - Tests service-owned mapping and embedding status fallback.
- Modify: `src/agentmind/panel/server.py`
  - Imports and constructs `SettingsStatusService`.
  - Delegates three read-side handlers to service methods.
- Modify: `tests/test_panel_api.py`
  - Adds delegation tests for the three panel endpoints.
- Modify: `tests/test_panel_control_plane_boundary.py`
  - Reclassifies the three read-side handlers as service-backed.
- Modify: `docs/phase3/panel-control-plane-boundary.md`
  - Updates target/transition lists.

## Tasks

### Task 1: RED Service Tests

- [ ] **Step 1: Write failing service tests**

Add tests for:

- `get_settings_view()` returns `memory`, `embedding`, `semantic_router`, `history`, and `meta` from `core_llm`.
- `get_feishu_config_view()` returns empty defaults when Feishu config is missing.
- `get_embedding_status()` reports external API, local model, dimension, and summary.
- `get_embedding_status()` treats local embedding probe failure as no local model.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_settings_status_service.py -q
```

Expected: FAIL because `SettingsStatusService` does not exist.

### Task 2: GREEN Service

- [ ] **Step 1: Implement `SettingsStatusService`**

Use dependency injection:

- `config_service`
- optional `local_embedding_probe`

Default `local_embedding_probe` imports and calls `agentmind.storage.embedding.has_local_embedding`.

- [ ] **Step 2: Run focused GREEN**

```bash
pytest tests/test_settings_status_service.py -q
```

Expected: PASS.

### Task 3: RED Panel Delegation

- [ ] **Step 1: Add panel delegation tests**

Monkeypatch `agentmind.panel.server.SettingsStatusService`, call:

- `GET /panel/api/settings`
- `GET /panel/api/feishu/config`
- `GET /panel/api/embedding/status`

Assert each response is returned from the service.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_settings_get_uses_settings_status_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_config_get_uses_settings_status_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_embedding_status_uses_settings_status_service -q
```

Expected: FAIL because panel still reads config and embedding status directly.

### Task 4: GREEN Panel Migration

- [ ] **Step 1: Migrate panel handlers**

Add `_settings_status_service()` helper and delegate:

- `feishu_get_config`
- `get_settings`
- `embedding_status`

- [ ] **Step 2: Update boundary audit**

Move `feishu_get_config`, `get_settings`, and `embedding_status` from transition to service-backed.

- [ ] **Step 3: Run focused GREEN**

```bash
pytest tests/test_settings_status_service.py tests/test_panel_api.py::TestPanelConfigServiceUsage::test_settings_get_uses_settings_status_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_config_get_uses_settings_status_service tests/test_panel_api.py::TestPanelConfigServiceUsage::test_embedding_status_uses_settings_status_service tests/test_panel_control_plane_boundary.py -q
```

Expected: PASS.

### Task 5: Verification

- [ ] **Step 1: Run panel regression**

```bash
pytest tests/test_panel_api.py -q
```

- [ ] **Step 2: Run service/config regression**

```bash
pytest tests/test_settings_status_service.py tests/test_settings_control_service.py tests/test_config_service.py -q
```

- [ ] **Step 3: Run architecture regression**

```bash
pytest tests/test_phase2_architecture_audit.py tests/test_panel_control_plane_boundary.py -q
```

- [ ] **Step 4: Run router/panel regression**

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

- [ ] **Step 5: Run full regression**

```bash
pytest -q
```

### Task 6: Commit

- [ ] **Step 1: Check diff hygiene**

```bash
git diff --check
git status --short
```

- [ ] **Step 2: Review and commit**

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-settings-status-service.md docs/phase3/panel-control-plane-boundary.md src/agentmind/services/settings_status_service.py src/agentmind/panel/server.py tests/test_settings_status_service.py tests/test_panel_api.py tests/test_panel_control_plane_boundary.py
git commit -m "refactor: route settings status views through service"
```

## Self-Review

- Spec coverage: Covers read-side settings/status views only.
- Placeholder scan: No TODO/TBD/fill-in markers.
- Architecture fit: Panel remains an adapter, service owns view assembly, config and embedding infrastructure stay below the service boundary.
