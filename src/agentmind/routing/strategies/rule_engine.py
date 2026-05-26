from agentmind.routing.context import RoutingContext
from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult


class RuleEngineStrategy(RoutingStrategy):
    """规则引擎策略：关键词/正则匹配。

    包装现有 RuleEngine.match()，但过滤 fallback 规则（confidence <= 0.5），
    由 SignalScoring 统一兜底。优先级 10。
    """

    def __init__(self, rule_engine):
        super().__init__(name="rule_engine", priority=10)
        self._engine = rule_engine

    async def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        result = await self._engine.match(ctx.raw_message)
        if result is None:
            return None
        # fallback 规则置信度 0.5，过滤后由 SignalScoring 兜底
        if result.confidence <= 0.5:
            return None
        # agentmind 自答
        if result.agent_id == "agentmind":
            return StrategyResult(
                agent_id="agentmind", confidence=0.9,
                reason=f"规则匹配(自答): {result.matched_rule}",
            )
        # 候选池为空（无健康 Agent）→ 弃权，让 SignalScoring 返回无可用
        if not ctx.candidates:
            return None
        # 验证 agent 在 L0 候选池中（健康且安全过滤通过）
        candidates = set(ctx.candidates)
        if result.agent_id not in candidates:
            return None
        return StrategyResult(
            agent_id=result.agent_id,
            confidence=result.confidence,
            reason=f"规则匹配: {result.matched_rule}",
        )
