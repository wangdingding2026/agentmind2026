import re

from agentmind.routing.context import RoutingContext
from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult


class ExplicitDirective(RoutingStrategy):
    """显式指令策略：@agent_name 指定目标 Agent。

    合并自 router.py 的 _step_explicit_prefix 和 _resolve_agent_mention。
    优先级最高（0），置信度 1.0。
    """

    def __init__(self, agent_registry):
        super().__init__(name="explicit", priority=0)
        self._registry = agent_registry

    async def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        m = re.match(r'@(\S+)', ctx.raw_message)
        if not m:
            return None
        agent_id = self._resolve(m.group(1))
        if not agent_id:
            return None
        # 候选池非空时验证 agent 在池中（健康检查）
        if ctx.candidates and agent_id not in ctx.candidates:
            return None
        return StrategyResult(
            agent_id=agent_id, confidence=1.0,
            reason=f"显式指定: @{agent_id}",
        )

    def _resolve(self, raw: str) -> str | None:
        # 精确 ID 匹配
        if self._registry.get_executor(raw):
            return raw
        raw_lower = raw.lower()
        for aid, ex in self._registry.executors.items():
            name = ex.capability.name.lower()
            if raw_lower == name:
                return aid
            if raw_lower in name or name in raw_lower:
                return aid
            if raw_lower in aid.lower():
                return aid
        return None
