# AgentMind Phase 3 Rule Control Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move panel route-rule management into a service-layer boundary.

**Architecture:** Add `RuleControlService` for control-plane route-rule CRUD. It composes `ConfigService` for `routes.yaml` reads/writes and owns rule-engine reload after mutations. `RuleEngine` remains the rule/core layer that matches messages; the service only manages rule configuration and reload lifecycle. The panel router delegates list/save/delete requests and performs only shallow request extraction.

**Tech Stack:** Python 3.12, FastAPI APIRouter, ConfigService, existing RuleEngine reload API, pytest, FastAPI TestClient.

---

## Architecture Constraints

Target architecture:

- Service layer does the work:
  - `RuleControlService.list_rules()` reads route rules through `ConfigService`.
  - `RuleControlService.save_rule()` builds the rule DTO, upserts by name, writes through `ConfigService`, and reloads the rule engine.
  - `RuleControlService.delete_rule()` removes by name, writes through `ConfigService`, and reloads the rule engine.
- Rule/core layer owns rule execution:
  - `RuleEngine` continues to parse, resolve, and match rules.
  - The service does not perform route matching.
- Panel layer stays thin:
  - Extracts request body and validates required `name`.
  - Delegates to `RuleControlService`.
  - Does not read/write routes config directly.
  - Does not call `rule_engine.reload()` directly.

Transition compatibility:

- Existing `/panel/api/rules` response shapes remain unchanged.
- Existing route YAML schema remains unchanged.
- Existing rule-engine reload behavior remains unchanged.
- No static front-end changes.

Not allowed:

- SQL/YAML route writes in panel.
- Route matching inside `RuleControlService`.
- New long-term panel helper for reload.
- Changing `RuleEngine` matching semantics.

Out of scope:

- Rule validation beyond current required name check.
- Rule preview/match explanation.
- StrategyManager ordering changes.
- Front-end UI changes.

## Files

Create:

- `src/agentmind/services/rule_control_service.py`
- `tests/test_rule_control_service.py`
- `docs/superpowers/plans/2026-05-27-phase-3-rule-control-service.md`

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
pytest tests/test_rule_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_rules_save_uses_rule_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_rules_delete_uses_rule_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_rule_engine.py tests/test_config_service.py tests/test_strategy_manager.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

---

### Task 1: RuleControlService

**Files:**

- Create: `src/agentmind/services/rule_control_service.py`
- Create: `tests/test_rule_control_service.py`
- Modify: `src/agentmind/services/__init__.py`

- [ ] **Step 1: Write RED service tests**

Add tests for:

- `list_rules()` returns rules from `ConfigService`.
- `save_rule()` upserts a rule, writes through `ConfigService`, reloads rule engine, and returns `{"ok": True, "name": ...}`.
- `delete_rule()` removes the rule, writes through `ConfigService`, reloads rule engine, and returns `{"ok": True}`.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_rule_control_service.py -q
```

Expected: FAIL because `RuleControlService` does not exist.

- [ ] **Step 3: Implement minimal service**

Create:

```python
class RuleControlService:
    def __init__(self, config_service=None, rule_engine=None):
        ...

    def list_rules(self) -> list[dict]:
        ...

    async def save_rule(self, rule_input: dict) -> dict:
        ...

    async def delete_rule(self, name: str) -> dict:
        ...
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_rule_control_service.py -q
```

Expected: PASS.

---

### Task 2: Panel Rules Delegation

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [ ] **Step 1: Write RED panel delegation tests**

Update/add tests to monkeypatch `RuleControlService` and assert:

- `GET /rules` calls `list_rules()`.
- `POST /rules` validates `name` and calls `save_rule(body)`.
- `DELETE /rules/{name}` calls `delete_rule(name)`.

- [ ] **Step 2: Verify RED**

Run focused panel tests.

Expected: FAIL because panel still uses `ConfigService` and `_reload_rule_engine` directly.

- [ ] **Step 3: Implement thin endpoint delegation**

Add helper:

```python
def _rule_control_service(request):
    return RuleControlService(
        config_service=ConfigService(CONFIG_DIR),
        rule_engine=request.app.state.rule_engine,
    )
```

Use it in list/save/delete endpoints.

- [ ] **Step 4: Verify GREEN**

Run focused panel tests and full panel tests.

---

## Final Verification

Run:

```bash
pytest tests/test_rule_control_service.py -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_rules_save_uses_rule_control_service -q
pytest tests/test_panel_api.py::TestPanelConfigServiceUsage::test_rules_delete_uses_rule_control_service -q
pytest tests/test_panel_api.py -q
pytest tests/test_rule_engine.py tests/test_config_service.py tests/test_strategy_manager.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-rule-control-service.md src/agentmind/services/rule_control_service.py src/agentmind/services/__init__.py src/agentmind/panel/server.py tests/test_rule_control_service.py tests/test_panel_api.py
git commit -m "refactor: route rule management through service"
```
