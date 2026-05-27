# AgentMind Phase 3 Agent Add Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel Agent creation and runtime registration into `AgentControlService`.

**Architecture:** `AgentControlService.add_cli_agent()` composes `AgentConfigService` for YAML-backed creation and owns runtime registration into `AgentRegistry`. The panel router only validates required request fields, parses tag strings, delegates to the service, and returns its response. This completes the Agent control-plane endpoint migration without changing routing rules or executor behavior.

**Tech Stack:** Python 3.12, FastAPI APIRouter, existing AgentCapability, CLIExecutor, AgentConfigService, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `AgentControlService.add_cli_agent()` persists Agent config through `AgentConfigService`.
  - It creates `AgentCapability` and `CLIExecutor`.
  - It registers the executor into runtime `AgentRegistry`.
- Panel layer stays thin:
  - Validates `id`, `name`, and `command`.
  - Parses comma-separated tags.
  - Calls `AgentControlService.add_cli_agent()`.
  - Does not instantiate `AgentCapability` or `CLIExecutor`.
- Rule/core layer is not involved:
  - Adding an Agent does not execute routing strategies or rules.

Transition compatibility:

- Existing `/panel/api/agents/add` response remains `{"ok": True}` on success.
- Existing request shape remains unchanged.
- Existing AgentConfigService write behavior remains unchanged.
- No static front-end changes.

Not allowed:

- Keeping runtime registration in panel.
- Duplicating YAML write logic in `AgentControlService`.
- Changing CLIExecutor behavior.
- Changing routing strategy behavior.

Out of scope:

- Adding non-CLI Agent types.
- Agent discovery scan.
- Bulk import.
- Validation beyond current required fields.

## Files

Modify:

- `src/agentmind/services/agent_control_service.py`
- `src/agentmind/panel/server.py`
- `tests/test_agent_control_service.py`
- `tests/test_panel_api.py`
- `docs/superpowers/plans/2026-05-27-phase-3-agent-add-service.md`

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
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_add_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_agent_control_service.py tests/test_agent_config_service.py tests/test_config_service.py tests/test_capability_registry.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: AgentControlService Add CLI Agent

**Files:**

- Modify: `src/agentmind/services/agent_control_service.py`
- Modify: `tests/test_agent_control_service.py`

- [ ] **Step 1: Write RED service test**

Add a test that:

- uses a fake `AgentConfigService.add_cli_agent()`.
- calls `AgentControlService.add_cli_agent(...)`.
- asserts returned value is `{"ok": True}`.
- asserts runtime registry now contains a CLI executor for the new Agent.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_agent_control_service.py -q
```

Expected: FAIL because `add_cli_agent()` does not exist.

- [ ] **Step 3: Implement minimal service method**

Add:

```python
def add_cli_agent(self, agent_id: str, name: str, command: str, tags: list[str]) -> dict[str, Any]:
    ...
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_agent_control_service.py -q
```

Expected: PASS.

---

### Task 2: Panel `/agents/add` Delegation

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel delegation test**

Update `TestPanelConfigServiceUsage::test_agent_add_uses_agent_config_service` into `test_agent_add_uses_agent_control_service`.

Assert:

- `AgentControlService.add_cli_agent()` receives parsed fields.
- endpoint returns the service response.
- panel no longer constructs runtime executor.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_add_uses_agent_control_service -q
```

Expected: FAIL because panel still calls `AgentConfigService` and registers runtime executor itself.

- [ ] **Step 3: Implement thin endpoint delegation**

Replace panel add logic after validation with:

```python
return _agent_control_service(request).add_cli_agent(agent_id, name, command, tags)
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_add_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_agent_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_agent_add_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_agent_control_service.py tests/test_agent_config_service.py tests/test_config_service.py tests/test_capability_registry.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-agent-add-service.md src/agentmind/services/agent_control_service.py src/agentmind/panel/server.py tests/test_agent_control_service.py tests/test_panel_api.py
git commit -m "refactor: route agent creation through service"
```
