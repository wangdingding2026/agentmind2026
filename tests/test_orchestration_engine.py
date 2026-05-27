import pytest

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType
from agentmind.api.models import OrchestrationPlan, OrchestrationStep


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


def test_api_orchestration_functions_delegate_to_default_engine(monkeypatch):
    import agentmind.api.orchestration as api_orchestration

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

    monkeypatch.setattr(api_orchestration, "_DEFAULT_ENGINE", FakeEngine(), raising=False)

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


class _StreamingExecutor:
    def __init__(self, agent_id, outputs):
        self.capability = AgentCapability(id=agent_id, name=f"{agent_id} name", type="cli")
        self.is_healthy = True
        self.outputs = outputs
        self.instructions = []

    async def execute_stream(self, instruction):
        self.instructions.append(instruction)
        for output in self.outputs:
            yield StreamEvent(StreamEventType.CONTENT, output)


class _Registry:
    def __init__(self, executors):
        self.executors = executors

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


@pytest.mark.asyncio
async def test_engine_execute_events_streams_ordered_step_events():
    from agentmind.orchestration.engine import OrchestrationEngine

    first = _StreamingExecutor("planner", ["plan"])
    second = _StreamingExecutor("writer", ["draft"])
    registry = _Registry({"planner": first, "writer": second})
    plan = OrchestrationPlan(
        plan_id="content-flow",
        steps=[
            OrchestrationStep(step_id=2, agent_id="writer", instruction="write", depends_on=[1]),
            OrchestrationStep(step_id=1, agent_id="planner", instruction="plan", depends_on=[]),
        ],
    )

    events = [event async for event in OrchestrationEngine().execute_events(plan, registry)]

    assert events == [
        {"event": "node_status", "data": {"step_id": 1, "status": "executing"}},
        {"event": "partial", "data": {"step_id": 1, "content": "plan"}},
        {"event": "node_status", "data": {"step_id": 1, "status": "completed"}},
        {"event": "node_status", "data": {"step_id": 2, "status": "executing"}},
        {"event": "partial", "data": {"step_id": 2, "content": "draft"}},
        {"event": "node_status", "data": {"step_id": 2, "status": "completed"}},
        {"event": "status", "data": {"status": "orchestration_complete", "plan_id": "content-flow"}},
    ]
    assert "前置步骤 1" in second.instructions[0]
    assert "plan" in second.instructions[0]
    assert "write" in second.instructions[0]


@pytest.mark.asyncio
async def test_engine_execute_events_reports_missing_executor():
    from agentmind.orchestration.engine import OrchestrationEngine

    plan = OrchestrationPlan(
        plan_id="missing-agent-flow",
        steps=[OrchestrationStep(step_id=1, agent_id="missing", instruction="run", depends_on=[])],
    )

    events = [event async for event in OrchestrationEngine().execute_events(plan, _Registry({}))]

    assert events == [
        {"event": "node_status", "data": {"step_id": 1, "status": "executing"}},
        {
            "event": "node_status",
            "data": {"step_id": 1, "status": "failed", "error": "Agent missing 不可用"},
        },
        {"event": "status", "data": {"status": "orchestration_complete", "plan_id": "missing-agent-flow"}},
    ]


@pytest.mark.asyncio
async def test_engine_execute_events_can_use_initial_instruction_for_root_steps():
    from agentmind.orchestration.engine import OrchestrationEngine

    executor = _StreamingExecutor("planner", ["plan"])
    registry = _Registry({"planner": executor})
    plan = OrchestrationPlan(
        plan_id="triggered-flow",
        steps=[OrchestrationStep(step_id=1, agent_id="planner", instruction="template", depends_on=[])],
    )

    _events = [
        event
        async for event in OrchestrationEngine().execute_events(
            plan,
            registry,
            initial_instruction="user asked for this specific task",
        )
    ]

    assert executor.instructions == ["user asked for this specific task"]
