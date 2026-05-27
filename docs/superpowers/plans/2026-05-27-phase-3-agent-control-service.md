# AgentMind Phase 3 Agent Control Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the panel Agent management read view into a service-layer boundary.

**Architecture:** Add `AgentControlService` for control-plane Agent DTO assembly. It reads runtime executors from `AgentRegistry`, masks sensitive config through `ConfigService`, and returns the existing panel response shape. The panel router delegates `/agents` to the service and does not iterate `registry.executors` or mask config itself.

**Tech Stack:** Python 3.12, FastAPI APIRouter, existing AgentRegistry, ConfigService, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `AgentControlService` builds Agent management view models.
  - `ConfigService` owns sensitive config masking.
  - `AgentConfigService` continues to own Agent configuration mutations.
- Rule/core layer owns rules:
  - No routing strategy or rule-engine logic belongs in the Agent management DTO.
- Panel layer stays thin:
  - `/panel/api/agents` only builds service dependencies and returns service output.
  - Panel does not traverse `registry.executors`.
  - Panel does not directly call config masking for Agent list assembly.

Transition compatibility:

- Existing `/panel/api/agents` response shape remains `{"agents": [...]}`.
- Existing Agent write endpoints remain on `AgentConfigService` in this package.
- No static front-end changes.

Not allowed:

- New direct YAML reads in panel.
- Long-term DTO assembly in panel.
- Moving write-side behavior into the read-view service.
- Changing Agent runtime registration semantics.

Out of scope:

- Agent write endpoint migration beyond the existing `AgentConfigService`.
- Agent health-check orchestration.
- CapabilityRegistry scoring changes.
- Front-end UI changes.

## Files

Create:

- `src/agentmind/services/agent_control_service.py`
- `tests/test_agent_control_service.py`
- `docs/superpowers/plans/2026-05-27-phase-3-agent-control-service.md`

Modify:

- `src/agentmind/panel/server.py`
- `src/agentmind/services/__init__.py`
- `tests/test_panel_api.py`

## Agent DTO Shape

Each Agent in `/panel/api/agents` keeps this shape:

```python
{
    "id": "mock_echo",
    "name": "Mock Echo",
    "type": "cli",
    "tags": ["code"],
    "enabled": True,
    "timeout": 5,
    "healthy": True,
    "last_health_check": "...",
    "description": "...",
    "security_level": "local",
    "estimated_cost": 0.0,
    "avg_latency": 0.0,
    "config": {"api_key": "****"},
}
```

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
pytest tests/test_panel_api.py::TestPanelAPI::test_agents_endpoint_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_agent_config_service.py tests/test_config_service.py tests/test_capability_registry.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: AgentControlService

**Files:**

- Create: `src/agentmind/services/agent_control_service.py`
- Create: `tests/test_agent_control_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- list_agents returns the existing panel DTO shape.
- sensitive config values are masked through `ConfigService`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_agent_control_service.py -q
```

Expected: FAIL because `AgentControlService` does not exist.

- [ ] **Step 3: Implement minimal service**

Create:

```python
class AgentControlService:
    def __init__(self, agent_registry, config_service=None):
        ...

    def list_agents(self) -> list[dict]:
        ...
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_agent_control_service.py -q
```

Expected: PASS.

---

### Task 2: Panel `/agents` Delegation

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel delegation test**

Add `TestPanelAPI::test_agents_endpoint_uses_agent_control_service` that monkeypatches `agentmind.panel.server.AgentControlService`, calls:

```text
GET /panel/api/agents
```

and asserts:

- Status is 200.
- Response is `{"agents": service_agents}`.
- Service constructor receives `request.app.state.agent_registry`.
- `list_agents()` is called.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_agents_endpoint_uses_agent_control_service -q
```

Expected: FAIL because `/agents` still assembles locally.

- [ ] **Step 3: Implement thin endpoint**

In `panel/server.py`:

- Import `AgentControlService`.
- Replace local executor traversal with:

```python
return {"agents": AgentControlService(request.app.state.agent_registry, ConfigService(CONFIG_DIR)).list_agents()}
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_agents_endpoint_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_agent_control_service.py -q
pytest tests/test_panel_api.py::TestPanelAPI::test_agents_endpoint_uses_agent_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_agent_config_service.py tests/test_config_service.py tests/test_capability_registry.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-agent-control-service.md src/agentmind/services/agent_control_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py tests/test_agent_control_service.py tests/test_panel_api.py
git commit -m "feat: add agent control service"
```
