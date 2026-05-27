# AgentMind Phase 3 Agent Runtime Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel Agent runtime actions into `AgentControlService`.

**Architecture:** Extend `AgentControlService` from read-only Agent management view assembly into the Agent control-plane action boundary. It composes `AgentConfigService` for YAML-backed mutations and owns runtime `AgentRegistry` synchronization. The panel router only validates request shape, delegates to the service, maps `None` results to 404, and returns service output.

**Tech Stack:** Python 3.12, FastAPI APIRouter, existing AgentRegistry executors, AgentConfigService, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `AgentControlService.restart_agent()` calls executor health check and returns runtime status.
  - `AgentControlService.update_tags()` persists tags through `AgentConfigService` and updates runtime capability.
  - `AgentControlService.toggle_enabled()` persists enabled state through `AgentConfigService` and updates runtime capability.
  - `AgentConfigService` remains the config-write boundary.
- Panel layer stays thin:
  - Validates obvious request shape, such as `tags` being a list.
  - Delegates Agent control actions to `AgentControlService`.
  - Does not fetch executors directly.
  - Does not mutate `executor.capability` directly.
- Rule/core layer is not involved:
  - Agent runtime actions do not execute routing rules or change strategy behavior.

Transition compatibility:

- Existing endpoint response shapes remain unchanged.
- Existing `/agents/add` remains out of scope for this package because it also creates runtime executor instances.
- Existing AgentConfigService tests remain valid.

Not allowed:

- Keeping executor lookup/mutation in panel for migrated endpoints.
- Duplicating YAML write logic in `AgentControlService`.
- Changing routing strategy behavior.
- Front-end/static UI changes.

Out of scope:

- `/agents/add` runtime registration migration.
- Bulk Agent actions.
- Agent health scheduling.
- CapabilityRegistry scoring changes.

## Files

Modify:

- `src/agentmind/services/agent_control_service.py`
- `src/agentmind/panel/server.py`
- `tests/test_agent_control_service.py`
- `tests/test_panel_api.py`
- `docs/superpowers/plans/2026-05-27-phase-3-agent-runtime-actions.md`

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_agent_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_restart_uses_agent_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_tags_uses_agent_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_toggle_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_agent_control_service.py tests/test_agent_config_service.py tests/test_config_service.py tests/test_capability_registry.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: AgentControlService Runtime Actions

**Files:**

- Modify: `src/agentmind/services/agent_control_service.py`
- Modify: `tests/test_agent_control_service.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- `restart_agent()` returns `None` for missing Agent and calls `health_check()` for existing Agent.
- `update_tags()` persists through `AgentConfigService`, updates runtime capability tags, and returns `{"ok": True, "tags": ...}`.
- `toggle_enabled()` persists through `AgentConfigService`, updates runtime capability enabled state, and returns `{"agent_id": ..., "enabled": ...}`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_agent_control_service.py -q
```

Expected: FAIL because runtime action methods do not exist.

- [ ] **Step 3: Implement minimal service methods**

Add optional `agent_config_service` dependency and the three action methods.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_agent_control_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Runtime Action Delegation

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel delegation tests**

Update or add tests that monkeypatch `AgentControlService` and assert:

- `/agents/{id}/restart` calls `restart_agent(id)`.
- `/agents/{id}/tags` calls `update_tags(id, tags)`.
- `/agents/{id}/toggle` calls `toggle_enabled(id)`.

- [ ] **Step 2: Verify RED**

Run the three focused panel tests.

Expected: FAIL because panel still performs executor lookup and calls `AgentConfigService` directly.

- [ ] **Step 3: Implement thin endpoint delegation**

Add helper:

```python
def _agent_control_service(request):
    return AgentControlService(
        request.app.state.agent_registry,
        config_service=ConfigService(CONFIG_DIR),
        agent_config_service=AgentConfigService(CONFIG_DIR),
    )
```

Use it in `/agents`, `/restart`, `/tags`, and `/toggle`.

- [ ] **Step 4: Verify GREEN**

Run focused panel tests and full panel tests.

---

## Final Verification

Run:

```bash
pytest tests/test_agent_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_restart_uses_agent_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_tags_uses_agent_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_toggle_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_agent_control_service.py tests/test_agent_config_service.py tests/test_config_service.py tests/test_capability_registry.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-agent-runtime-actions.md src/agentmind/services/agent_control_service.py src/agentmind/panel/server.py tests/test_agent_control_service.py tests/test_panel_api.py
git commit -m "refactor: route agent runtime actions through service"
```
