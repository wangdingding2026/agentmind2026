import logging

from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision

logger = logging.getLogger("agentmind")


class RoutingPipeline:
    def __init__(self, agent_registry, rule_engine):
        self._agent_registry = agent_registry
        self._rule_engine = rule_engine
        self._min_confidence = 0.7
        # 策略在第一次 run() 时惰性构建，避免循环引用
        self._strategies = None

    def _ensure_strategies(self):
        if self._strategies is not None:
            return
        from agentmind.routing.strategies.explicit_directive import ExplicitDirective
        from agentmind.routing.strategies.memory_recall import MemoryRecallStrategy
        from agentmind.routing.strategies.rule_engine import RuleEngineStrategy
        from agentmind.routing.strategies.llm_routing import LLMRoutingStrategy
        from agentmind.routing.strategies.signal_scoring import SignalScoringStrategy

        self._strategies = [
            ExplicitDirective(self._agent_registry),
            MemoryRecallStrategy(),
            RuleEngineStrategy(self._rule_engine),
            LLMRoutingStrategy(self._agent_registry, {}),  # settings 在 run() 注入
            SignalScoringStrategy(self._agent_registry),
        ]

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
        self._ensure_strategies()

        # 动态更新 LLMRouting 的 settings（每次请求可能不同）
        for s in self._strategies:
            if s.name == "llm_routing":
                s._settings = settings

        sorted_strategies = sorted(self._strategies, key=lambda s: s.priority)
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
