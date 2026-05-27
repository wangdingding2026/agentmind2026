# AgentMind Phase 3 Agent Config Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel agent configuration writes out of endpoint code and into a service boundary that inherits ConfigService auditing.

**Architecture:** Add `AgentConfigService` for agent-specific configuration mutations: add/replace CLI agents, update tags, and toggle enabled state. It composes `ConfigService` for YAML persistence, so config writes continue to be audited through the existing ConfigService/AuditService path. Panel endpoints keep runtime registry updates where needed, but no longer read or write `agents.yaml` directly.

**Tech Stack:** Python 3.12, YAML ConfigService, AgentCapability/CLIExecutor runtime registration, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- `AgentConfigService`
  - Owns agent config mutation semantics.
  - Reads/writes agents through `ConfigService`.
  - Returns plain dicts for panel/runtime registration.
- `ConfigService`
  - Remains the only YAML persistence boundary.
  - Continues to emit audit events for `write_agents()`.
- Panel endpoints
  - Validate HTTP request shape.
  - Call `AgentConfigService` for persistent config changes.
  - Keep runtime executor updates as adapter behavior for this package.

Transition compatibility:

- `agents/add` still immediately registers the new CLI executor in the in-memory registry after service persistence.
- `agents/{id}/tags` and `agents/{id}/toggle` still update the in-memory executor capability after service persistence.
- Existing endpoint responses remain unchanged.

Not allowed:

- Keeping direct `yaml.safe_load` / `path.write_text` agent config writes in panel endpoints.
- Adding endpoint-level audit calls; audit must flow through `ConfigService.write_agents()`.
- Replacing AgentRegistry runtime behavior in this package.
- Touching deleted files.

Out of scope:

- Full AgentService lifecycle.
- Agent health/restart refactor.
- Agent discovery write-path refactor.
- Non-CLI agent creation UI.

## Files

Create:

- `src/agentmind/services/agent_config_service.py`
- `tests/test_agent_config_service.py`

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
pytest tests/test_agent_config_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: AgentConfigService Owns Agent YAML Mutations

**Files:**

- Create: `tests/test_agent_config_service.py`
- Create: `src/agentmind/services/agent_config_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [x] **Step 1: Write RED tests**

Create tests covering:

- `add_cli_agent()` replaces existing agent with same id and calls `ConfigService.write_agents()`.
- `update_tags()` updates the target agent tags and returns the tags.
- `toggle_enabled()` flips enabled and returns the new state.
- Missing agent operations return `None`.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_agent_config_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.agent_config_service'`.

- [x] **Step 3: Implement AgentConfigService**

Add:

- `AgentConfigService(config_dir=None, config_service=None)`
- `add_cli_agent(agent_id, name, command, tags) -> dict`
- `update_tags(agent_id, tags) -> list[str] | None`
- `toggle_enabled(agent_id, current_enabled=None) -> bool | None`

Use only `ConfigService.read_agents()` and `ConfigService.write_agents()` for persistence.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_agent_config_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Agent Writes Delegate To AgentConfigService

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [x] **Step 1: Write RED panel delegation tests**

Add tests under `TestPanelConfigServiceUsage` that monkeypatch `agentmind.panel.server.AgentConfigService` and assert:

- `/panel/api/agents/add` calls `add_cli_agent(...)`.
- `/panel/api/agents/{id}/tags` calls `update_tags(...)`.
- `/panel/api/agents/{id}/toggle` calls `toggle_enabled(...)`.

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
```

Expected: FAIL because panel still directly reads/writes `agents.yaml`.

- [x] **Step 3: Migrate panel endpoints**

In `panel/server.py`:

- Import `AgentConfigService`.
- Remove direct `yaml` and `shlex` use if no longer needed.
- `agents/add`: call `AgentConfigService(CONFIG_DIR).add_cli_agent(...)`, then use returned dict to register `CLIExecutor`.
- `agents/{id}/tags`: call `update_tags(...)`, then update in-memory executor tags.
- `agents/{id}/toggle`: call `toggle_enabled(...)`, then update in-memory executor enabled.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_agent_config_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_agent_config_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-agent-config-service.md tests/test_agent_config_service.py tests/test_panel_api.py src/agentmind/services/agent_config_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py
git commit -m "refactor: route panel agent config writes through service"
```
