from agentmind.routing.context import RoutingContext
from agentmind.routing.strategies.base import RoutingStrategy, StrategyResult


class SignalScoringStrategy(RoutingStrategy):
    """信号评分策略：按成本/延迟/安全评分选最优 Agent。

    最后执行（priority=100），永不弃权——候选池空时自动取全部健康 Agent。
    合并自 router.py 的 _step_signal_drive + _step_fallback。
    """

    def __init__(self, agent_registry):
        super().__init__(name="signal_scoring", priority=100)
        self._registry = agent_registry

    async def evaluate(self, ctx: RoutingContext) -> StrategyResult:
        if ctx.candidates:
            best = self._score_best(ctx.candidates, is_retry=ctx.is_retry)
            alternatives = [a for a in ctx.candidates if a != best]
            return StrategyResult(
                agent_id=best, confidence=0.3,
                reason="信号评分兜底",
                alternatives=alternatives,
            )
        # 候选池为空且安全标记时，不回退到全部 Agent（防止敏感信息泄露到云端）
        if ctx.security_flagged:
            return StrategyResult(agent_id="", confidence=0.0, reason="无可用本地Agent（安全拦截）")
        # 候选池为空时取全部健康 Agent
        all_healthy = [
            aid for aid, ex in self._registry.executors.items() if ex.is_healthy
        ]
        if all_healthy:
            best = self._score_best(all_healthy, is_retry=ctx.is_retry)
            return StrategyResult(
                agent_id=best, confidence=0.2,
                reason="全局兜底（无候选）",
            )
        return StrategyResult(agent_id="", confidence=0.0, reason="无可用Agent")

    def _score_best(self, candidates: list[str], is_retry: bool) -> str:
        scored = []
        for aid in candidates:
            ex = self._registry.get_executor(aid)
            if not ex:
                continue
            scored.append((aid, self._score_agent(ex, is_retry)))
        if not scored:
            return ""
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def _score_agent(self, executor, is_retry: bool) -> float:
        cap = executor.capability
        cost_score = 1.0 - min(1.0, cap.estimated_cost / 0.1)
        latency_score = 1.0 - min(1.0, cap.avg_latency / 10.0)
        security_score = 1.0
        if is_retry:
            return 0.2 * cost_score + 0.4 * latency_score + 0.4 * security_score
        return 0.4 * cost_score + 0.3 * latency_score + 0.3 * security_score
