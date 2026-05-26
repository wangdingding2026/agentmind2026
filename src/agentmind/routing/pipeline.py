import logging

from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision

logger = logging.getLogger("agentmind")


class RoutingPipeline:
    def __init__(self, agent_registry, rule_engine, strategy_manager=None):
        self._agent_registry = agent_registry
        self._rule_engine = rule_engine
        self._min_confidence = 0.7
        if strategy_manager is None:
            from agentmind.services.strategy_manager import StrategyManager

            strategy_manager = StrategyManager(agent_registry, rule_engine)
        self._strategy_manager = strategy_manager

    async def run(
        self, message: str, identity: RequestIdentity,
        settings: dict, is_retry: bool = False,
    ) -> RoutingDecision:
        # ── L0: 前置中间件 ──
        from agentmind.routing.middleware.sensitive_scanner import SensitiveScanner
        from agentmind.routing.middleware.candidate_pool import CandidatePool
        from agentmind.routing.middleware.memory_retriever import MemoryRetriever

        scan_result = SensitiveScanner().scan(message)
        candidates = CandidatePool(self._agent_registry).filter(scan_result)

        try:
            memories = await MemoryRetriever().retrieve(message, identity.user_id)
        except Exception:
            logger.debug("MemoryRetriever 检索失败，使用空记忆", exc_info=True)
            memories = []

        ctx = RoutingContext(
            identity=identity,
            raw_message=message,
            candidates=candidates,
            memories=memories,
            security_flagged=scan_result.flagged,
            is_retry=is_retry,
        )

        # ── L1: 意图分类 ──
        from agentmind.routing.classifier.intent import Intent, IntentClassifier
        intent = IntentClassifier().classify(ctx)

        if intent != Intent.SINGLE_TASK:
            return RoutingDecision(
                agent_id="", strategy="unsupported",
                confidence=0.0, context=ctx,
            )

        # ── L2: 策略管道 ──
        return await self._run_strategies(ctx, settings, is_retry)

    async def _run_strategies(
        self, ctx: RoutingContext, settings: dict, is_retry: bool,
    ) -> RoutingDecision:
        sorted_strategies = self._strategy_manager.get_enabled_strategies(settings)
        for i, strategy in enumerate(sorted_strategies):
            result = await strategy.evaluate(ctx)
            if result is None:
                continue
            is_last = (i == len(sorted_strategies) - 1)
            if is_last or result.confidence >= self._min_confidence:
                return RoutingDecision(
                    agent_id=result.agent_id,
                    strategy=result.reason,
                    confidence=result.confidence,
                    fallback_chain=result.alternatives,
                    reply_text=result.reply_text,
                    context=ctx,
                )

        # 不应到达（SignalScoring 永不弃权）
        return RoutingDecision(
            agent_id="", strategy="error", confidence=0.0, context=ctx,
        )
