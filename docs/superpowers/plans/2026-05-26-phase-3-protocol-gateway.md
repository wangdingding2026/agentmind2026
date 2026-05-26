# AgentMind Phase 3 ProtocolGateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ProtocolGateway service that exposes one protocol-neutral interface for CLI, HTTP/API, MCP, and A2A agent invocation while preserving existing executor behavior.

**Architecture:** Keep current `agents/*_executor.py` classes as the execution implementations. Add connector wrappers under `src/agentmind/connectors/` and a service entrypoint in `src/agentmind/services/protocol_gateway.py` that exposes `invoke`, `stream`, `health`, and `capabilities`. Migrate the low-risk shared non-streaming fallback path in `routing/executors/base.py` to use the gateway; leave broad streaming route migration for a later package after the gateway contract is stable.

**Tech Stack:** Python 3.12, async iterators, dataclasses, pytest, pytest-asyncio.

---

## Phase 3 Scope

This package implements Phase 3 item 2 of 6: `ProtocolGateway`.

Completed earlier:

- `StrategyManager` foundation: `6479ef1 feat: add strategy manager`.

Out of scope for this package:

- `AgentCapabilityRegistry`.
- `OrchestrationEngine`.
- `AuditService`.
- Full panel control-plane redesign.
- Deleting or merging legacy executor classes.

## Files

Create:

- `src/agentmind/connectors/__init__.py`
- `src/agentmind/connectors/base.py`
- `src/agentmind/connectors/cli.py`
- `src/agentmind/connectors/http.py`
- `src/agentmind/connectors/mcp.py`
- `src/agentmind/connectors/a2a.py`
- `src/agentmind/services/protocol_gateway.py`
- `tests/test_protocol_gateway.py`

Modify:

- `src/agentmind/routing/executors/base.py`
- `tests/test_pipeline_executors.py`

Do not modify:

- `src/agentmind/agents/*_executor.py` unless a focused test exposes a wrapper incompatibility.
- `src/agentmind/api/router.py`
- `src/agentmind/api/orchestration.py`
- Deleted file `记忆和检索模块优化方案.md`.

## Strict TDD And Verification

For each task:

1. Write the focused failing test.
2. Run that exact test and confirm the expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run the related regressions.

Package verification:

```bash
pytest tests/test_protocol_gateway.py -q
pytest tests/test_pipeline_executors.py::TestExecutorBase -q
pytest tests/test_cli_executor.py tests/test_api_executor.py tests/test_mcp_executor.py tests/test_a2a_executor.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: ProtocolGateway Contract

**Files:**

- Create: `tests/test_protocol_gateway.py`
- Create: `src/agentmind/connectors/__init__.py`
- Create: `src/agentmind/connectors/base.py`
- Create: `src/agentmind/connectors/cli.py`
- Create: `src/agentmind/connectors/http.py`
- Create: `src/agentmind/connectors/mcp.py`
- Create: `src/agentmind/connectors/a2a.py`
- Create: `src/agentmind/services/protocol_gateway.py`

- [x] **Step 1: Write RED tests**

Create `tests/test_protocol_gateway.py`:

```python
import pytest

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType, TaskResult


class _FakeExecutor:
    def __init__(self, capability, *, healthy=True):
        self.capability = capability
        self.is_healthy = healthy
        self.last_health_check = None
        self.invocations = []

    async def execute(self, instruction: str, context: dict = None):
        self.invocations.append(("execute", instruction, context))
        return TaskResult(success=True, output=f"{self.capability.type}:{instruction}", execution_time_ms=7)

    async def execute_stream(self, instruction: str, context: dict = None):
        self.invocations.append(("stream", instruction, context))
        yield StreamEvent(StreamEventType.CONTENT, f"{self.capability.type}:{instruction}")

    async def health_check(self):
        self.last_health_check = "checked"
        return self.is_healthy


class _Registry:
    def __init__(self, executors):
        self.executors = executors

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


def _executor(agent_id: str, protocol: str, *, healthy=True):
    cap = AgentCapability(
        id=agent_id,
        name=f"{protocol} agent",
        type=protocol,
        tags=["test"],
        enabled=True,
        timeout=5,
        config={},
    )
    return _FakeExecutor(cap, healthy=healthy)


@pytest.mark.parametrize("protocol", ["cli", "api", "mcp", "a2a"])
@pytest.mark.asyncio
async def test_protocol_gateway_invokes_all_supported_protocols(protocol):
    from agentmind.services.protocol_gateway import ProtocolGateway

    executor = _executor("agent1", protocol)
    gateway = ProtocolGateway(_Registry({"agent1": executor}))

    result = await gateway.invoke("agent1", "hello", context={"trace_id": "t1"})

    assert result.success is True
    assert result.output == f"{protocol}:hello"
    assert executor.invocations == [("execute", "hello", {"trace_id": "t1"})]


@pytest.mark.asyncio
async def test_protocol_gateway_streams_agent_events():
    from agentmind.services.protocol_gateway import ProtocolGateway

    executor = _executor("agent1", "cli")
    gateway = ProtocolGateway(_Registry({"agent1": executor}))

    events = [event async for event in gateway.stream("agent1", "hello")]

    assert [event.text for event in events] == ["cli:hello"]


@pytest.mark.asyncio
async def test_protocol_gateway_returns_failed_result_for_unavailable_agent():
    from agentmind.services.protocol_gateway import ProtocolGateway

    gateway = ProtocolGateway(_Registry({}))

    result = await gateway.invoke("missing", "hello")

    assert result.success is False
    assert "不可用" in result.error
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_protocol_gateway.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.services.protocol_gateway'`.

- [x] **Step 3: Implement gateway and connector wrappers**

Add:

- `AgentConnector` base class with `invoke`, `stream`, `health`, `capabilities`.
- `ExecutorConnector` implementation that delegates to existing executor instances.
- Thin `CLIConnector`, `HTTPConnector`, `MCPConnector`, and `A2AConnector` classes that inherit `ExecutorConnector`.
- `ProtocolGateway` that resolves an executor from `AgentRegistry`, selects a connector by `capability.type`, and exposes `invoke`, `stream`, `health`, `capabilities`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_protocol_gateway.py -q
```

Expected: PASS.

---

### Task 2: ExecutorBase Uses ProtocolGateway For Non-Streaming Fallback

**Files:**

- Modify: `tests/test_pipeline_executors.py`
- Modify: `src/agentmind/routing/executors/base.py`

- [x] **Step 1: Write RED test**

Add a test proving `_execute_with_fallback` delegates invocation through `ProtocolGateway`:

```python
    @pytest.mark.asyncio
    async def test_execute_with_fallback_invokes_protocol_gateway(self, monkeypatch):
        from agentmind.agents.base import TaskResult

        ex1 = _mock_executor(succeed=True, output="direct-result")
        reg = _mock_registry({"a1": ex1})

        calls = []

        class FakeGateway:
            def __init__(self, registry):
                self.registry = registry

            async def invoke(self, agent_id, instruction, context=None):
                calls.append((agent_id, instruction, context))
                return TaskResult(success=True, output="gateway-result")

        monkeypatch.setattr("agentmind.routing.executors.base.ProtocolGateway", FakeGateway)

        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = reg

        aid, result, error = await base._execute_with_fallback(["a1"], "msg")

        assert aid == "a1"
        assert result.output == "gateway-result"
        assert calls == [("a1", "msg", None)]
        assert error is None
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_pipeline_executors.py::TestExecutorBase::test_execute_with_fallback_invokes_protocol_gateway -q
```

Expected: FAIL because `agentmind.routing.executors.base` has no `ProtocolGateway` symbol or direct executor result remains `direct-result`.

- [x] **Step 3: Wire ExecutorBase to ProtocolGateway**

Change `ExecutorBase`:

- Import `ProtocolGateway`.
- Add `_gateway = ProtocolGateway(agent_registry)` in `__init__`.
- In `_execute_with_fallback`, call `self._gateway.invoke(agent_id, envelope)` after `_find_executor` confirms health.
- Keep `__new__`-constructed tests compatible by lazily creating `_gateway` when missing.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_pipeline_executors.py::TestExecutorBase -q
pytest tests/test_protocol_gateway.py -q
```

Expected: PASS.

---

### Task 3: Executor Regression And Full Verification

**Files:**

- No production files unless tests expose regressions.

- [x] **Step 1: Run protocol executor regression**

Run:

```bash
pytest tests/test_cli_executor.py tests/test_api_executor.py tests/test_mcp_executor.py tests/test_a2a_executor.py -q
```

Expected: PASS. Existing executors must remain unchanged behaviorally.

- [x] **Step 2: Run routing and panel regression**

Run:

```bash
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
```

Expected: PASS.

- [x] **Step 3: Run full suite and legacy deletion check**

Run:

```bash
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/superpowers/plans/2026-05-26-phase-3-protocol-gateway.md src/agentmind/connectors src/agentmind/services/protocol_gateway.py src/agentmind/routing/executors/base.py tests/test_protocol_gateway.py tests/test_pipeline_executors.py
git commit -m "feat: add protocol gateway"
```

Expected: commit succeeds and `git status --short` is clean.

## Self-Review

- Spec coverage: covers ProtocolGateway `invoke`, `stream`, `health`, and `capabilities`, plus one low-risk production path migration.
- Scope check: does not implement CapabilityRegistry, OrchestrationEngine, AuditService, or full streaming migration.
- Placeholder scan: no TODO/TBD placeholders.
- Type consistency: gateway uses existing `TaskResult`, `StreamEvent`, and `AgentCapability` types.
