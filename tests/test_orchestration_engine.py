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
