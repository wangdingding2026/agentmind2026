# AgentMind Phase 3 CapabilityRegistry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AgentCapabilityRegistry service that exposes agent capability profiles for routing and the control panel.

**Architecture:** Build a read-focused service over the existing `AgentRegistry`, `ProtocolGateway`, and task metrics. Do not add a new persistence table in this package; derive health and static capability data from executors, and derive success/error stats from existing task metrics. Route scoring should read normalized capability profiles through this service while retaining executor fallback compatibility.

**Tech Stack:** Python 3.12, dataclasses, FastAPI panel API, pytest, pytest-asyncio.

---

## Phase 3 Scope

This package implements Phase 3 item 3 of 6: `AgentCapabilityRegistry`.

Completed earlier:

- `StrategyManager` foundation: `6479ef1 feat: add strategy manager`.
- `ProtocolGateway` foundation: `566b142 feat: add protocol gateway`.

Out of scope for this package:

- New database tables for agent performance history.
- Control panel write APIs for editing capability profiles.
- OrchestrationEngine.
- AuditService.
- Full panel control-plane redesign.

## Files

Create:

- `src/agentmind/services/capability_registry.py`
- `tests/test_capability_registry.py`

Modify:

- `src/agentmind/routing/strategies/signal_scoring.py`
- `src/agentmind/panel/server.py`
- `tests/test_router.py`
- `tests/test_panel_api.py`

Do not modify:

- `src/agentmind/agents/*_executor.py`
- `src/agentmind/services/protocol_gateway.py`
- `src/agentmind/api/router.py`
- Deleted file `记忆和检索模块优化方案.md`.

## Strict TDD And Verification

For each task:

1. Write the focused failing test.
2. Run that exact test and confirm the expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_capability_registry.py -q
pytest tests/test_router.py::TestRouter::test_signal_scoring_picks_low_cost -q
pytest tests/test_panel_api.py::TestPanelAPI::test_agent_capabilities_endpoint -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: CapabilityRegistry Service

**Files:**

- Create: `tests/test_capability_registry.py`
- Create: `src/agentmind/services/capability_registry.py`

- [x] **Step 1: Write RED tests**

Create `tests/test_capability_registry.py`:

```python
from agentmind.agents.base import AgentCapability


class _Executor:
    def __init__(self, capability, *, healthy=True, last_health_check="2026-05-26T00:00:00Z"):
        self.capability = capability
        self.is_healthy = healthy
        self.last_health_check = last_health_check


class _Registry:
    def __init__(self, executors):
        self.executors = executors

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


def _cap(agent_id, *, protocol="cli", tags=None, cost=0.0, latency=0.0, security="local"):
    return AgentCapability(
        id=agent_id,
        name=f"{agent_id} name",
        type=protocol,
        tags=tags or [],
        enabled=True,
        timeout=5,
        description=f"{agent_id} desc",
        security_level=security,
        estimated_cost=cost,
        avg_latency=latency,
        config={},
    )


def test_capability_registry_lists_profiles_with_runtime_health_and_metrics():
    from agentmind.services.capability_registry import AgentCapabilityRegistry

    registry = _Registry({
        "cheap": _Executor(_cap("cheap", tags=["code"], cost=0.001, latency=1.5)),
        "cloud": _Executor(_cap("cloud", protocol="api", security="cloud", cost=0.1, latency=8), healthy=False),
    })
    metrics = {
        "by_agent": {
            "cheap": {"total": 4, "errors": 1, "error_rate": 0.25},
        }
    }

    profiles = AgentCapabilityRegistry(registry, metrics_provider=lambda: metrics).list_profiles()

    assert [p["agent_id"] for p in profiles] == ["cheap", "cloud"]
    assert profiles[0]["protocol"] == "cli"
    assert profiles[0]["tags"] == ["code"]
    assert profiles[0]["healthy"] is True
    assert profiles[0]["success_rate"] == 0.75
    assert profiles[0]["recent_error_count"] == 1
    assert profiles[1]["healthy"] is False
    assert profiles[1]["success_rate"] is None


def test_capability_registry_get_profile_returns_none_for_unknown_agent():
    from agentmind.services.capability_registry import AgentCapabilityRegistry

    registry = _Registry({})

    assert AgentCapabilityRegistry(registry).get_profile("missing") is None
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_capability_registry.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.capability_registry'`.

- [x] **Step 3: Implement AgentCapabilityRegistry**

Add a service with:

- `list_profiles() -> list[dict]`
- `get_profile(agent_id) -> dict | None`
- `score_inputs(agent_id) -> dict | None`
- `record_health(agent_id, healthy) -> dict | None`

Profiles must include:

- `agent_id`, `name`, `protocol`, `tags`, `description`
- `security_level`, `estimated_cost`, `avg_latency`
- `healthy`, `last_health_check`
- `success_rate`, `recent_error_count`

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_capability_registry.py -q
```

Expected: PASS.

---

### Task 2: SignalScoring Reads CapabilityRegistry

**Files:**

- Modify: `src/agentmind/routing/strategies/signal_scoring.py`
- Modify: `tests/test_router.py`

- [x] **Step 1: Write RED test**

Update `tests/test_router.py::TestRouter::test_signal_scoring_picks_low_cost` to monkeypatch the capability registry and assert the scoring strategy reads it:

```python
        calls = []

        class FakeCapabilityRegistry:
            def __init__(self, registry):
                self.registry = registry

            def score_inputs(self, agent_id):
                calls.append(agent_id)
                if agent_id == "cheap":
                    return {"estimated_cost": 0.001, "avg_latency": 1.0, "security_level": "local", "success_rate": 1.0}
                if agent_id == "costly":
                    return {"estimated_cost": 0.5, "avg_latency": 10.0, "security_level": "local", "success_rate": 1.0}
                return None

        monkeypatch.setattr("agentmind.routing.strategies.signal_scoring.AgentCapabilityRegistry", FakeCapabilityRegistry)
```

Change the test signature to include `monkeypatch` and assert:

```python
        assert calls == ["cheap", "costly"]
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_router.py::TestRouter::test_signal_scoring_picks_low_cost -q
```

Expected: FAIL because `AgentCapabilityRegistry` is not imported or calls remain empty.

- [x] **Step 3: Wire SignalScoringStrategy to AgentCapabilityRegistry**

Change `SignalScoringStrategy`:

- Create `self._capabilities = AgentCapabilityRegistry(agent_registry)`.
- In `_score_agent`, use `self._capabilities.score_inputs(cap.id)` first.
- Fall back to `executor.capability` if profile is missing.
- Include a small success-rate component without changing the low-cost test outcome.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_router.py::TestRouter::test_signal_scoring_picks_low_cost -q
pytest tests/test_capability_registry.py -q
```

Expected: PASS.

---

### Task 3: Panel Capability Endpoint

**Files:**

- Modify: `src/agentmind/panel/server.py`
- Modify: `tests/test_panel_api.py`

- [x] **Step 1: Write RED panel test**

Add to `TestPanelAPI`:

```python
    def test_agent_capabilities_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            app, mp = make_panel_app(tmp_dir)
            client = TestClient(app)
            try:
                resp = client.get("/panel/api/agents/capabilities")
                assert resp.status_code == 200
                data = resp.json()
                assert "capabilities" in data
                profile = data["capabilities"][0]
                assert profile["agent_id"] == "mock_echo"
                assert profile["protocol"] == "cli"
                assert profile["healthy"] is True
                assert "success_rate" in profile
            finally:
                mp.undo()
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_agent_capabilities_endpoint -q
```

Expected: FAIL with HTTP 404 for `/panel/api/agents/capabilities`.

- [x] **Step 3: Add panel endpoint**

Add:

```text
GET /panel/api/agents/capabilities
```

It should instantiate `AgentCapabilityRegistry(request.app.state.agent_registry)` and return `{"capabilities": ...}`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_panel_api.py::TestPanelAPI::test_agent_capabilities_endpoint -q
pytest tests/test_panel_api.py -q
```

Expected: PASS.

---

### Task 4: Final Verification And Commit

- [x] **Step 1: Run package verification**

Run:

```bash
pytest tests/test_capability_registry.py -q
pytest tests/test_router.py::TestRouter::test_signal_scoring_picks_low_cost -q
pytest tests/test_panel_api.py::TestPanelAPI::test_agent_capabilities_endpoint -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

Expected: PASS.

- [ ] **Step 2: Commit**

Run:

```bash
git add docs/superpowers/plans/2026-05-26-phase-3-capability-registry.md src/agentmind/services/capability_registry.py src/agentmind/routing/strategies/signal_scoring.py src/agentmind/panel/server.py tests/test_capability_registry.py tests/test_router.py tests/test_panel_api.py
git commit -m "feat: add capability registry"
```

Expected: commit succeeds and `git status --short` is clean.

## Self-Review

- Spec coverage: covers capability profiles, protocol type, tags, security level, cost, latency, success rate, recent error count, panel visibility, and routing read path.
- Scope check: avoids database schema changes and panel write APIs.
- Placeholder scan: no TODO/TBD placeholders.
- Type consistency: uses existing `AgentCapability` fields and existing task metrics shape.
