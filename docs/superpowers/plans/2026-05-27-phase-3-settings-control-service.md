# AgentMind Phase 3 Settings Control Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel settings and Feishu config save payload assembly into a service-layer boundary.

**Architecture:** Add `SettingsControlService` for control-plane settings updates. It composes `ConfigService`, maps panel request fields to settings sections, and returns the existing endpoint responses. `ConfigService` remains the YAML read/write and audit boundary. The panel router delegates save requests and does not build settings section payloads itself.

**Tech Stack:** Python 3.12, FastAPI APIRouter, ConfigService, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `SettingsControlService.save_settings()` maps panel payload keys into settings sections.
  - `SettingsControlService.save_feishu_config()` maps Feishu config payload into the `feishu` section.
  - `ConfigService` owns YAML writes and audit event emission.
- Panel layer stays thin:
  - Reads request JSON.
  - Delegates payload to `SettingsControlService`.
  - Returns service output.
- Channel behavior is out of scope:
  - Feishu connect/disconnect runtime lifecycle remains unchanged for now.
  - ChannelHub migration is Phase 4 scope.

Transition compatibility:

- Existing `/panel/api/settings` response remains `{"ok": True}`.
- Existing `/panel/api/feishu/config` POST response remains `{"ok": True}`.
- Existing `/panel/api/feishu/config` GET response remains unchanged.
- Existing request shapes remain unchanged.

Not allowed:

- Keeping settings section mapping in panel for migrated endpoints.
- Duplicating YAML write logic in the new service.
- Changing ConfigService audit behavior.
- Changing Feishu runtime connection behavior in this package.

Out of scope:

- Feishu connect/disconnect lifecycle migration.
- Settings validation beyond current behavior.
- Front-end/static UI changes.
- ChannelHub.

## Files

Create:

- `src/agentmind/services/settings_control_service.py`
- `tests/test_settings_control_service.py`
- `docs/superpowers/plans/2026-05-27-phase-3-settings-control-service.md`

Modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/services/__init__.py`
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
pytest tests/test_settings_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_settings_save_uses_settings_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_config_save_uses_settings_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_config_service.py tests/test_audit_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: SettingsControlService

**Files:**

- Create: `src/agentmind/services/settings_control_service.py`
- Create: `tests/test_settings_control_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- `save_settings()` maps `meta` to `core_llm` and preserves `memory`, `embedding`, `semantic_router`, and `history`.
- `save_feishu_config()` writes the `feishu` section with `enabled`, `app_id`, and `app_secret`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_settings_control_service.py -q
```

Expected: FAIL because `SettingsControlService` does not exist.

- [ ] **Step 3: Implement minimal service**

Create:

```python
class SettingsControlService:
    def __init__(self, config_service=None, config_dir=None):
        ...

    def save_settings(self, body: dict) -> dict:
        ...

    def save_feishu_config(self, body: dict) -> dict:
        ...
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_settings_control_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Delegation

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel delegation tests**

Update/add tests that monkeypatch `SettingsControlService` and assert:

- `/settings` POST calls `save_settings(body)`.
- `/feishu/config` POST calls `save_feishu_config(body)`.

- [ ] **Step 2: Verify RED**

Run focused panel tests.

Expected: FAIL because panel still builds sections directly and calls `ConfigService`.

- [ ] **Step 3: Implement thin endpoint delegation**

Add helper:

```python
def _settings_control_service():
    return SettingsControlService(config_service=ConfigService(CONFIG_DIR))
```

Use it in POST `/settings` and POST `/feishu/config`.

- [ ] **Step 4: Verify GREEN**

Run focused panel tests and full panel tests.

---

## Final Verification

Run:

```bash
pytest tests/test_settings_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_settings_save_uses_settings_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_feishu_config_save_uses_settings_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_config_service.py tests/test_audit_service.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-settings-control-service.md src/agentmind/services/settings_control_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py tests/test_settings_control_service.py tests/test_panel_api.py
git commit -m "refactor: route settings saves through service"
```
