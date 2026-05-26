# AgentMind Phase 3 StrategyManager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a StrategyManager service so routing strategies are registered, ordered, enabled, and inspected through a service boundary instead of being hard-coded inside `RoutingPipeline`.

**Architecture:** Keep existing strategy classes and routing behavior, but move strategy construction and ordering into `src/agentmind/services/strategy_manager.py`. `RoutingPipeline` will ask the manager for enabled strategy instances on every run, allowing runtime enable/disable and order changes without changing `router.py`. The four protected core strategies are `explicit`, `rule_engine`, `llm_routing`, and `signal_scoring`; existing `memory_recall` remains an auxiliary migration strategy so Phase 2 memory recall behavior does not regress.

**Tech Stack:** Python 3.12, asyncio, dataclasses, FastAPI panel API, pytest, pytest-asyncio.

---

## Phase 3 Scope

Phase 3 target packages from the project plans:

- `ProtocolGateway`: unify CLI / HTTP / MCP / A2A invocation.
- `AgentCapabilityRegistry`: expose agent capability profiles.
- `StrategyManager`: make routing strategies manageable and hot-swappable.
- `OrchestrationEngine`: centralize DAG validation and execution.

This package implements only `StrategyManager`. Protocol gateway, capability registry, orchestration engine, audit service, and full panel control-plane redesign remain out of scope.

## Files

Create:

- `src/agentmind/services/strategy_manager.py`
- `tests/test_strategy_manager.py`

Modify:

- `src/agentmind/routing/pipeline.py`
- `src/agentmind/startup.py`
- `src/agentmind/panel/server.py`
- `tests/test_pipeline_executors.py`
- `tests/test_panel_api.py`

Do not modify:

- `src/agentmind/api/router.py` except if a later audit proves it directly constructs strategy lists.
- `src/agentmind/memory/service.py`
- `src/agentmind/storage/memory.py`
- Deleted file `记忆和检索模块优化方案.md`.

## Strict TDD And Verification

For each task:

1. Write the focused failing test.
2. Run that exact test and confirm the expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regression commands.

Package verification:

```bash
pytest tests/test_strategy_manager.py -q
pytest tests/test_pipeline_executors.py::TestRoutingPipeline -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_rule_engine.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: StrategyManager Service

**Files:**

- Create: `tests/test_strategy_manager.py`
- Create: `src/agentmind/services/strategy_manager.py`

- [x] **Step 1: Write RED tests**

Create tests proving the manager exposes the protected core strategy order, supports auxiliary strategy inspection, and can disable a non-required strategy at runtime:

```python
import pytest


class _Registry:
    executors = {}

    def get_executor(self, agent_id):
        return None


class _RuleEngine:
    async def match(self, message):
        return None


def test_strategy_manager_lists_core_and_auxiliary_strategies():
    from agentmind.services.strategy_manager import StrategyManager

    manager = StrategyManager(_Registry(), _RuleEngine())

    names = [item["name"] for item in manager.list_strategies()]
    core_names = [item["name"] for item in manager.list_strategies(kind="core")]
    auxiliary_names = [item["name"] for item in manager.list_strategies(kind="auxiliary")]

    assert core_names == ["explicit", "rule_engine", "llm_routing", "signal_scoring"]
    assert "memory_recall" in auxiliary_names
    assert names.index("memory_recall") < names.index("rule_engine")


def test_strategy_manager_can_disable_non_required_strategy():
    from agentmind.services.strategy_manager import StrategyManager

    manager = StrategyManager(_Registry(), _RuleEngine())

    assert manager.set_enabled("llm_routing", False)["enabled"] is False

    enabled_names = [strategy.name for strategy in manager.get_enabled_strategies({})]
    assert "llm_routing" not in enabled_names
    assert enabled_names[-1] == "signal_scoring"
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_strategy_manager.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.strategy_manager'`.

- [x] **Step 3: Implement StrategyManager**

Create `StrategyManager` with:

- Default registrations for `explicit`, `memory_recall`, `rule_engine`, `llm_routing`, and `signal_scoring`.
- `list_strategies(kind=None)`.
- `set_enabled(name, enabled)`.
- `set_order(names)`.
- `get_enabled_strategies(settings)`.
- Guardrails that prevent disabling `explicit`, `rule_engine`, and `signal_scoring`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_strategy_manager.py -q
```

Expected: PASS.

---

### Task 2: RoutingPipeline Uses StrategyManager

**Files:**

- Modify: `tests/test_pipeline_executors.py`
- Modify: `src/agentmind/routing/pipeline.py`

- [x] **Step 1: Write RED test**

Add a focused pipeline test proving the pipeline does not own a hard-coded strategy list and respects an injected manager with `llm_routing` disabled:

```python
    @pytest.mark.asyncio
    async def test_pipeline_uses_strategy_manager_for_enabled_strategies(self):
        from agentmind.routing.pipeline import RoutingPipeline
        from agentmind.routing.context import RequestIdentity
        from agentmind.services.strategy_manager import StrategyManager

        ex1 = _mock_executor(healthy=True)
        reg = _mock_registry({"a1": ex1})

        class _NoRuleEngine:
            async def match(self, message):
                return None

        manager = StrategyManager(reg, _NoRuleEngine())
        manager.set_enabled("llm_routing", False)
        pipeline = RoutingPipeline(reg, _NoRuleEngine(), strategy_manager=manager)

        decision = await pipeline.run("hello", RequestIdentity(trace_id="t1", user_id="u1"), {})

        assert decision.agent_id == "a1"
        assert "llm_routing" not in [s.name for s in manager.get_enabled_strategies({})]
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_pipeline_executors.py::TestRoutingPipeline::test_pipeline_uses_strategy_manager_for_enabled_strategies -q
```

Expected: FAIL with `TypeError: RoutingPipeline.__init__() got an unexpected keyword argument 'strategy_manager'`.

- [x] **Step 3: Wire RoutingPipeline to StrategyManager**

Change `RoutingPipeline.__init__` to accept optional `strategy_manager`. If omitted, create `StrategyManager(agent_registry, rule_engine)`. Replace `_ensure_strategies()` with `self._strategy_manager.get_enabled_strategies(settings)` inside `_run_strategies()`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_pipeline_executors.py::TestRoutingPipeline -q
pytest tests/test_strategy_manager.py -q
```

Expected: PASS.

---

### Task 3: Startup And Panel Inspection

**Files:**

- Modify: `src/agentmind/startup.py`
- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [x] **Step 1: Write RED panel test**

Add a panel API test for strategy inspection:

```python
    def test_strategy_status_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/routing/strategies")
                assert resp.status_code == 200
                data = resp.json()
                core = [s["name"] for s in data["strategies"] if s["kind"] == "core"]
                assert core == ["explicit", "rule_engine", "llm_routing", "signal_scoring"]
                assert any(s["name"] == "memory_recall" and s["kind"] == "auxiliary" for s in data["strategies"])
            finally:
                mp.undo()
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_strategy_status_endpoint -q
```

Expected: FAIL with HTTP 404 for `/panel/api/routing/strategies`.

- [x] **Step 3: Add startup state and panel route**

In startup, create one `StrategyManager` and pass it to `RoutingPipeline`. In panel, add:

```text
GET /panel/api/routing/strategies
```

The endpoint should read `request.app.state.strategy_manager` when available and create a temporary manager from `agent_registry` and `rule_engine` as a compatibility fallback for tests or older app assembly.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_strategy_status_endpoint -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

## Final Verification

Run:

```bash
pytest tests/test_strategy_manager.py -q
pytest tests/test_pipeline_executors.py::TestRoutingPipeline -q
pytest tests/test_panel_api.py -q
pytest tests/test_router.py tests/test_rule_engine.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

Expected:

```text
All pytest commands pass.
Deleted legacy plan file remains absent.
```

## Self-Review

- Spec coverage: covers Phase 3 StrategyManager requirements for registration, enable/disable, order, routing pipeline integration, and control panel inspection.
- Scope check: does not implement ProtocolGateway, CapabilityRegistry, OrchestrationEngine, AuditService, or full panel redesign.
- Placeholder scan: no TODO/TBD placeholders.
- Type consistency: strategy names match current strategy class names: `explicit`, `memory_recall`, `rule_engine`, `llm_routing`, `signal_scoring`.
