# AgentMind Phase 3 OrchestrationEngine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the first OrchestrationEngine package by moving pure DAG validation, ordering, and context injection logic out of the API layer.

**Architecture:** Create `agentmind.orchestration` as the stable orchestration domain boundary. This first package keeps execution paths unchanged and makes `api/orchestration.py` compatibility functions delegate to `OrchestrationEngine`, so later work can migrate execution without duplicating DAG rules.

**Tech Stack:** Python 3.12, Pydantic models, FastAPI compatibility layer, pytest.

---

## Phase 3 Scope

This package implements the low-risk first slice of Phase 3 item 4: `OrchestrationEngine`.

Completed earlier:

- `StrategyManager`: `6479ef1 feat: add strategy manager`.
- `ProtocolGateway`: `566b142 feat: add protocol gateway`.
- `AgentCapabilityRegistry`: `02c945f feat: add capability registry`.

In scope for this package:

- Add `src/agentmind/orchestration/__init__.py`.
- Add `src/agentmind/orchestration/models.py`.
- Add `src/agentmind/orchestration/engine.py`.
- Add `tests/test_orchestration_engine.py`.
- Move pure DAG operations into `OrchestrationEngine`:
  - `validate_dag`
  - `topological_sort`
  - `build_contextual_instruction`
- Keep `agentmind.api.orchestration` functions as compatibility wrappers.

Out of scope for this package:

- Migrating `execute_dag_plan`.
- Migrating `services/routing_service.py::_match_orchestration`.
- Migrating `services/routing_service.py::_execute_orchestration_plan`.
- Adding parallel DAG execution, retries, skip/stop policy, or trace schema.
- AuditService.
- ChannelHub or Phase 4 work.
- Restoring deleted file `记忆和检索模块优化方案.md`.

## Files

Create:

- `src/agentmind/orchestration/__init__.py`
- `src/agentmind/orchestration/models.py`
- `src/agentmind/orchestration/engine.py`
- `tests/test_orchestration_engine.py`

Modify:

- `src/agentmind/api/orchestration.py`

Do not modify:

- `src/agentmind/services/routing_service.py`
- `src/agentmind/api/router.py`
- `src/agentmind/panel/server.py`
- Deleted file `记忆和检索模块优化方案.md`

## Strict TDD And Verification

For every behavior:

1. Write the focused failing test.
2. Run that exact test and confirm the expected failure.
3. Implement the smallest production change.
4. Run the focused test and confirm GREEN.
5. Run related regressions.

Package verification:

```bash
pytest tests/test_orchestration_engine.py -q
pytest tests/test_orchestration.py -q
pytest tests/test_orchestration.py tests/test_router.py tests/test_e2e_scenarios.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

---

### Task 1: OrchestrationEngine Pure DAG Boundary

**Files:**

- Create: `tests/test_orchestration_engine.py`
- Create: `src/agentmind/orchestration/__init__.py`
- Create: `src/agentmind/orchestration/models.py`
- Create: `src/agentmind/orchestration/engine.py`

- [x] **Step 1: Write RED tests**

Create `tests/test_orchestration_engine.py`:

```python
import pytest

from agentmind.api.models import OrchestrationStep


def test_engine_validates_and_sorts_diamond_dag():
    from agentmind.orchestration.engine import OrchestrationEngine

    steps = [
        OrchestrationStep(step_id=1, agent_id="planner", instruction="plan", depends_on=[]),
        OrchestrationStep(step_id=2, agent_id="researcher", instruction="research", depends_on=[1]),
        OrchestrationStep(step_id=3, agent_id="coder", instruction="code", depends_on=[1]),
        OrchestrationStep(step_id=4, agent_id="reviewer", instruction="review", depends_on=[2, 3]),
    ]

    engine = OrchestrationEngine()

    engine.validate_dag(steps)
    ordered = engine.topological_sort(steps)

    ordered_ids = [step.step_id for step in ordered]
    assert ordered_ids[0] == 1
    assert ordered_ids[-1] == 4
    assert set(ordered_ids[1:3]) == {2, 3}


def test_engine_rejects_cycle():
    from agentmind.orchestration.engine import OrchestrationEngine

    steps = [
        OrchestrationStep(step_id=1, agent_id="a", instruction="1", depends_on=[2]),
        OrchestrationStep(step_id=2, agent_id="b", instruction="2", depends_on=[1]),
    ]

    with pytest.raises(ValueError, match="循环依赖"):
        OrchestrationEngine().validate_dag(steps)


def test_engine_builds_contextual_instruction_from_available_dependencies_only():
    from agentmind.orchestration.engine import OrchestrationEngine

    step = OrchestrationStep(
        step_id=3,
        agent_id="reviewer",
        instruction="summarize",
        depends_on=[1, 2],
    )

    instruction = OrchestrationEngine().build_contextual_instruction(
        step,
        {1: "planner output"},
    )

    assert "前置步骤 1" in instruction
    assert "planner output" in instruction
    assert "前置步骤 2" not in instruction
    assert "summarize" in instruction
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_orchestration_engine.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmind.orchestration'`.

- [x] **Step 3: Implement minimal engine package**

Create `src/agentmind/orchestration/models.py`:

```python
from agentmind.api.models import OrchestrationPlan, OrchestrationStep

__all__ = ["OrchestrationPlan", "OrchestrationStep"]
```

Create `src/agentmind/orchestration/engine.py` with `OrchestrationEngine` methods:

- `validate_dag(steps: list[OrchestrationStep]) -> None`
- `topological_sort(steps: list[OrchestrationStep]) -> list[OrchestrationStep]`
- `build_contextual_instruction(step: OrchestrationStep, previous_results: dict[int, str]) -> str`

Create `src/agentmind/orchestration/__init__.py` exporting `OrchestrationEngine`, `OrchestrationPlan`, and `OrchestrationStep`.

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_orchestration_engine.py -q
```

Expected: PASS.

---

### Task 2: API Compatibility Delegates To Engine

**Files:**

- Modify: `src/agentmind/api/orchestration.py`
- Modify: `tests/test_orchestration_engine.py`

- [x] **Step 1: Write RED compatibility test**

Append to `tests/test_orchestration_engine.py`:

```python
def test_api_orchestration_functions_delegate_to_default_engine(monkeypatch):
    import agentmind.api.orchestration as api_orchestration
    from agentmind.api.models import OrchestrationStep

    calls = []

    class FakeEngine:
        def validate_dag(self, steps):
            calls.append(("validate", [step.step_id for step in steps]))

        def topological_sort(self, steps):
            calls.append(("sort", [step.step_id for step in steps]))
            return list(reversed(steps))

        def build_contextual_instruction(self, step, previous_results):
            calls.append(("context", step.step_id, dict(previous_results)))
            return "delegated"

    monkeypatch.setattr(api_orchestration, "_DEFAULT_ENGINE", FakeEngine())

    steps = [
        OrchestrationStep(step_id=1, agent_id="a", instruction="one", depends_on=[]),
        OrchestrationStep(step_id=2, agent_id="b", instruction="two", depends_on=[1]),
    ]

    api_orchestration.validate_dag(steps)
    ordered = api_orchestration.topological_sort(steps)
    instruction = api_orchestration.build_contextual_instruction(steps[1], {1: "result"})

    assert [step.step_id for step in ordered] == [2, 1]
    assert instruction == "delegated"
    assert calls == [
        ("validate", [1, 2]),
        ("sort", [1, 2]),
        ("context", 2, {1: "result"}),
    ]
```

- [x] **Step 2: Verify RED**

Run:

```bash
pytest tests/test_orchestration_engine.py::test_api_orchestration_functions_delegate_to_default_engine -q
```

Expected: FAIL because `api_orchestration.validate_dag`, `topological_sort`, and `build_contextual_instruction` still contain local logic and do not call `_DEFAULT_ENGINE`.

- [x] **Step 3: Replace API pure logic with wrappers**

In `src/agentmind/api/orchestration.py`:

- Remove direct `defaultdict` and `deque` imports if unused.
- Import `OrchestrationEngine`.
- Add `_DEFAULT_ENGINE = OrchestrationEngine()`.
- Change compatibility functions to:

```python
def validate_dag(steps: list[OrchestrationStep]):
    return _DEFAULT_ENGINE.validate_dag(steps)


def topological_sort(steps: list[OrchestrationStep]) -> list[OrchestrationStep]:
    return _DEFAULT_ENGINE.topological_sort(steps)


def build_contextual_instruction(step: OrchestrationStep, previous_results: dict[int, str]) -> str:
    return _DEFAULT_ENGINE.build_contextual_instruction(step, previous_results)
```

- [x] **Step 4: Verify GREEN**

Run:

```bash
pytest tests/test_orchestration_engine.py -q
pytest tests/test_orchestration.py -q
```

Expected: PASS.

---

## Final Verification

Run all required verification commands:

```bash
pytest tests/test_orchestration_engine.py -q
pytest tests/test_orchestration.py -q
pytest tests/test_orchestration.py tests/test_router.py tests/test_e2e_scenarios.py -q
pytest tests/test_router.py tests/test_panel_api.py tests/test_feishu_path.py tests/test_e2e_scenarios.py tests/test_pipeline_executors.py -q
pytest -q
test ! -e '记忆和检索模块优化方案.md'
```

If all commands pass, commit:

```bash
git add docs/superpowers/plans/2026-05-27-phase-3-orchestration-engine.md tests/test_orchestration_engine.py src/agentmind/orchestration/__init__.py src/agentmind/orchestration/models.py src/agentmind/orchestration/engine.py src/agentmind/api/orchestration.py
git commit -m "feat: add orchestration engine"
```
