"""DAG 编排测试"""
import pytest
from pydantic import BaseModel


class TestValidateDAG:
    def test_no_cycle(self):
        from agentmind.api.orchestration import validate_dag
        from agentmind.api.models import OrchestrationStep

        steps = [
            OrchestrationStep(step_id=1, agent_id="a", instruction="step1", depends_on=[]),
            OrchestrationStep(step_id=2, agent_id="b", instruction="step2", depends_on=[1]),
            OrchestrationStep(step_id=3, agent_id="c", instruction="step3", depends_on=[1, 2]),
        ]
        validate_dag(steps)  # 不抛异常

    def test_cycle_detected(self):
        from agentmind.api.orchestration import validate_dag
        from agentmind.api.models import OrchestrationStep

        steps = [
            OrchestrationStep(step_id=1, agent_id="a", instruction="1", depends_on=[3]),
            OrchestrationStep(step_id=2, agent_id="b", instruction="2", depends_on=[1]),
            OrchestrationStep(step_id=3, agent_id="c", instruction="3", depends_on=[2]),
        ]
        with pytest.raises(ValueError, match="循环依赖"):
            validate_dag(steps)

    def test_self_loop(self):
        from agentmind.api.orchestration import validate_dag
        from agentmind.api.models import OrchestrationStep

        steps = [OrchestrationStep(step_id=1, agent_id="a", instruction="x", depends_on=[1])]
        with pytest.raises(ValueError):
            validate_dag(steps)


class TestTopologicalSort:
    def test_linear(self):
        from agentmind.api.orchestration import topological_sort
        from agentmind.api.models import OrchestrationStep

        steps = [
            OrchestrationStep(step_id=1, agent_id="a", instruction="1", depends_on=[]),
            OrchestrationStep(step_id=2, agent_id="b", instruction="2", depends_on=[1]),
        ]
        result = topological_sort(steps)
        assert [s.step_id for s in result] == [1, 2]

    def test_diamond(self):
        from agentmind.api.orchestration import topological_sort
        from agentmind.api.models import OrchestrationStep

        steps = [
            OrchestrationStep(step_id=1, agent_id="a", instruction="1", depends_on=[]),
            OrchestrationStep(step_id=2, agent_id="b", instruction="2", depends_on=[1]),
            OrchestrationStep(step_id=3, agent_id="c", instruction="3", depends_on=[1]),
            OrchestrationStep(step_id=4, agent_id="d", instruction="4", depends_on=[2, 3]),
        ]
        result = topological_sort(steps)
        ids = [s.step_id for s in result]
        assert ids[0] == 1
        assert ids[3] == 4
        assert set(ids[1:3]) == {2, 3}

    def test_invalid_raises(self):
        from agentmind.api.orchestration import topological_sort
        from agentmind.api.models import OrchestrationStep

        steps = [
            OrchestrationStep(step_id=1, agent_id="a", instruction="1", depends_on=[2]),
            OrchestrationStep(step_id=2, agent_id="b", instruction="2", depends_on=[1]),
        ]
        with pytest.raises(ValueError):
            topological_sort(steps)


class TestContextualInstruction:
    def test_no_deps(self):
        from agentmind.api.orchestration import build_contextual_instruction
        from agentmind.api.models import OrchestrationStep

        step = OrchestrationStep(step_id=1, agent_id="a", instruction="hello", depends_on=[])
        assert build_contextual_instruction(step, {}) == "hello"

    def test_with_deps(self):
        from agentmind.api.orchestration import build_contextual_instruction
        from agentmind.api.models import OrchestrationStep

        step = OrchestrationStep(step_id=2, agent_id="b", instruction="analyze", depends_on=[1])
        prev = {1: "result from step 1"}
        result = build_contextual_instruction(step, prev)
        assert "前置步骤 1" in result
        assert "result from step 1" in result
        assert "analyze" in result

    def test_missing_dep(self):
        from agentmind.api.orchestration import build_contextual_instruction
        from agentmind.api.models import OrchestrationStep

        step = OrchestrationStep(step_id=2, agent_id="b", instruction="x", depends_on=[99])
        assert build_contextual_instruction(step, {}) == "x"
