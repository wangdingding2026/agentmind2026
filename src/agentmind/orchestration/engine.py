"""Core DAG orchestration logic."""

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from agentmind.orchestration.models import OrchestrationPlan, OrchestrationStep


MemoryWriter = Callable[[OrchestrationStep, str, str], Awaitable[None]]


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

    async def execute_events(
        self,
        plan: OrchestrationPlan,
        agent_registry,
        memory_writer: MemoryWriter | None = None,
        initial_instruction: str = "",
    ):
        """Execute a DAG plan and yield normalized orchestration events."""
        self.validate_dag(plan.steps)
        sorted_steps = self.topological_sort(plan.steps)
        step_results: dict[int, str] = {}

        for step in sorted_steps:
            yield {"event": "node_status", "data": {
                "step_id": step.step_id,
                "status": "executing",
            }}

            executor = agent_registry.get_executor(step.agent_id)
            if executor is None or not getattr(executor, "is_healthy", True):
                yield {"event": "node_status", "data": {
                    "step_id": step.step_id,
                    "status": "failed",
                    "error": f"Agent {step.agent_id} 不可用",
                }}
                continue

            if initial_instruction and not step.depends_on:
                instruction = initial_instruction
            else:
                instruction = self.build_contextual_instruction(step, step_results)
            full_output: list[str] = []
            failed = False

            try:
                async for event in executor.execute_stream(instruction):
                    if event.type.value == "content":
                        full_output.append(event.text)
                        yield {"event": "partial", "data": {
                            "step_id": step.step_id,
                            "content": event.text,
                        }}
                    elif event.type.value == "error":
                        failed = True
                        yield {"event": "node_status", "data": {
                            "step_id": step.step_id,
                            "status": "failed",
                            "error": event.text,
                        }}
                        break
            except Exception as exc:
                failed = True
                yield {"event": "node_status", "data": {
                    "step_id": step.step_id,
                    "status": "failed",
                    "error": str(exc),
                }}

            if failed:
                continue

            result = "".join(full_output)
            step_results[step.step_id] = result[:4000]
            if memory_writer is not None:
                await memory_writer(step, plan.plan_id, result)

            yield {"event": "node_status", "data": {
                "step_id": step.step_id,
                "status": "completed",
            }}

        yield {"event": "status", "data": {
            "status": "orchestration_complete",
            "plan_id": plan.plan_id,
        }}
