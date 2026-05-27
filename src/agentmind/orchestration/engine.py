"""Core DAG orchestration logic."""

from collections import defaultdict, deque

from agentmind.orchestration.models import OrchestrationStep


class OrchestrationEngine:
    """Validates DAG plans and prepares step instructions."""

    def validate_dag(self, steps: list[OrchestrationStep]) -> None:
        """DFS cycle detection. Raises ValueError when the DAG is invalid."""
        visited: set[int] = set()
        rec_stack: set[int] = set()
        step_map = {step.step_id: step for step in steps}

        def dfs(step_id: int) -> None:
            if step_id in rec_stack:
                raise ValueError(f"检测到循环依赖，涉及步骤 {step_id}")
            if step_id in visited:
                return
            visited.add(step_id)
            rec_stack.add(step_id)
            step = step_map.get(step_id)
            if step:
                for dep in step.depends_on:
                    dfs(dep)
            rec_stack.discard(step_id)

        for step in steps:
            dfs(step.step_id)

    def topological_sort(self, steps: list[OrchestrationStep]) -> list[OrchestrationStep]:
        """Kahn topological sort for sequential DAG execution."""
        in_degree: dict[int, int] = defaultdict(int)
        children: dict[int, list[int]] = defaultdict(list)
        step_map = {step.step_id: step for step in steps}

        for step in steps:
            for dep in step.depends_on:
                in_degree[step.step_id] += 1
                children[dep].append(step.step_id)

        queue = deque([step.step_id for step in steps if in_degree[step.step_id] == 0])
        sorted_steps: list[OrchestrationStep] = []

        while queue:
            step_id = queue.popleft()
            step = step_map[step_id]
            sorted_steps.append(step)
            for child in children[step_id]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(sorted_steps) != len(steps):
            raise ValueError("拓扑排序失败，可能存在循环依赖")
        return sorted_steps

    def build_contextual_instruction(
        self,
        step: OrchestrationStep,
        previous_results: dict[int, str],
    ) -> str:
        """Inject available dependency results into the current step prompt."""
        if not step.depends_on:
            return step.instruction

        parts = []
        for dep_id in step.depends_on:
            if dep_id in previous_results:
                parts.append(f"前置步骤 {dep_id} 的输出：\n{previous_results[dep_id]}")

        if not parts:
            return step.instruction

        injected = "\n\n".join(parts)
        return (
            "[系统注入：前置依赖的执行结果摘要]\n"
            f"{injected}\n\n"
            "（注意：以上内容可能被截断，如需完整细节请通过记忆检索获取）\n\n"
            "请基于以上前置结果，执行当前任务：\n"
            f"{step.instruction}"
        )
