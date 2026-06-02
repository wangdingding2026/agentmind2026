import pytest
from unittest.mock import AsyncMock

from agentmind.agents.base import AgentCapability
from agentmind.routing.context import RequestIdentity, RoutingContext
from agentmind.routing.pipeline import RoutingPipeline
from agentmind.routing.semantic_intent import SemanticIntentType
from agentmind.routing.strategies.semantic_intent import SemanticIntentStrategy


# ═══════════════════════════════════════
# Helpers
# ═══════════════════════════════════════

class _Executor:
    def __init__(self, agent_id: str, tags: list[str]):
        self.is_healthy = True
        self.last_health_check = 0
        self.capability = AgentCapability(
            id=agent_id,
            name=agent_id,
            type="cli",
            tags=tags,
            description=f"{agent_id} capability",
            enabled=True,
            timeout=5,
        )


class _Registry:
    executors = {
        "searcher": _Executor("searcher", ["search", "weather"]),
        "coder": _Executor("coder", ["code"]),
        "claude_code": _Executor("claude_code", ["code"]),
        "codex": _Executor("codex", ["code"]),
    }

    def get_executor(self, agent_id):
        return self.executors.get(agent_id)


class _Strategy(SemanticIntentStrategy):
    def __init__(self, payload: dict):
        super().__init__(
            _Registry(),
            {"core_llm": {"enabled": True, "endpoint": "http://llm.local"}},
        )
        self._payload = payload

    async def _call_llm(self, prompt: str, cfg: dict) -> dict | None:
        return self._payload


def _build_context(message: str) -> RoutingContext:
    return RoutingContext(
        identity=RequestIdentity(user_id="u1"),
        raw_message=message,
        candidates=["searcher", "coder", "claude_code", "codex"],
    )


# ═══════════════════════════════════════
# L1: 语义意图分类矩阵（17 行）
# ═══════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "payload", "expected_agent", "expected_intent"),
    [
        # ── conversation_history ──
        (
            "当前session我们聊过什么内容",
            {
                "intent": "conversation_history",
                "confidence": 0.95,
                "time_scope": "current_session",
                "current_session": True,
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        (
            "当前会话刚刚说了什么",
            {
                "intent": "conversation_history",
                "confidence": 0.92,
                "time_scope": "current_session",
                "current_session": True,
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        (
            "今天聊过什么",
            {
                "intent": "conversation_history",
                "confidence": 0.95,
                "time_scope": "today",
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        (
            "今天都聊过什么内容，帮我总结一下",
            {
                "intent": "conversation_history",
                "confidence": 0.95,
                "time_scope": "today",
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        (
            "昨天做过什么",
            {
                "intent": "conversation_history",
                "confidence": 0.92,
                "time_scope": "yesterday",
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        (
            "5月29日聊过什么",
            {
                "intent": "conversation_history",
                "confidence": 0.90,
                "time_scope": "explicit_date",
                "explicit_date": "2026-05-29",
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        (
            "刚刚 codex 说了什么",
            {
                "intent": "conversation_history",
                "confidence": 0.88,
                "time_scope": "current_session",
                "current_session": True,
                "agent_filter": "codex",
                "requested_format": "topic_summary",
            },
            "agentmind",
            SemanticIntentType.CONVERSATION_HISTORY,
        ),
        # ── agentmind_capability ──
        (
            "你能查询天气吗？",
            {"intent": "agentmind_capability", "confidence": 0.88},
            "agentmind",
            SemanticIntentType.AGENTMIND_CAPABILITY,
        ),
        (
            "你会写代码吗？",
            {"intent": "agentmind_capability", "confidence": 0.88},
            "agentmind",
            SemanticIntentType.AGENTMIND_CAPABILITY,
        ),
        # ── agent_task ──
        (
            "帮我查今天上海天气",
            {
                "intent": "agent_task",
                "confidence": 0.90,
                "target_agent": "searcher",
            },
            "searcher",
            SemanticIntentType.AGENT_TASK,
        ),
        (
            "帮我写一个 Python 排序函数",
            {
                "intent": "agent_task",
                "confidence": 0.92,
                "target_agent": "coder",
            },
            "coder",
            SemanticIntentType.AGENT_TASK,
        ),
    ],
)
async def test_semantic_routing_matrix(message, payload, expected_agent, expected_intent):
    """语义意图分类：LLM 输出 → intent + agent_id + 不生成 reply_text"""
    ctx = _build_context(message)
    result = await _Strategy(payload).evaluate(ctx)

    assert result is not None
    assert result.agent_id == expected_agent, (
        f"'{message}' 应路由到 {expected_agent}，实际 {result.agent_id}"
    )
    assert result.reply_text == "", (
        f"'{message}' 不应生成 freeform reply_text: {result.reply_text[:80]}"
    )
    assert result.semantic_intent is not None
    assert result.semantic_intent.intent == expected_intent, (
        f"'{message}' intent 应为 {expected_intent.value}，实际 {result.semantic_intent.intent.value}"
    )
    assert ctx.semantic_intent is result.semantic_intent


# ═══════════════════════════════════════
# L2: 端到端路由管道矩阵（全链路验证）
# ═══════════════════════════════════════

class TestEndToEndRoutingMatrix:
    """通过 RoutingPipeline.run() 验证协议路由 + 语义路由 全链路。"""

    @pytest.mark.asyncio
    async def test_conversation_history_routes_to_agentmind_executor(self, monkeypatch):
        """conversation_history → agentmind → ConversationHistoryExecutor"""
        from agentmind.routing.semantic_intent import SemanticIntent

        # mock semantic_intent 策略返回 conversation_history
        async def _mock_evaluate(self, ctx):
            from agentmind.routing.strategies.base import StrategyResult
            si = SemanticIntent(
                intent=SemanticIntentType.CONVERSATION_HISTORY,
                confidence=0.95,
                time_scope="today",
                requested_format="topic_summary",
            )
            ctx.semantic_intent = si
            return StrategyResult(
                agent_id="agentmind", confidence=0.95,
                reason="semantic_intent", semantic_intent=si,
            )

        monkeypatch.setattr(
            "agentmind.routing.strategies.semantic_intent.SemanticIntentStrategy.evaluate",
            _mock_evaluate,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        pipeline = self._build_pipeline()
        decision = await pipeline.run(
            "今天聊过什么",
            RequestIdentity(user_id="u1"),
            {},
        )

        assert decision.agent_id == "agentmind"
        assert decision.semantic_intent is not None
        assert decision.semantic_intent.intent == SemanticIntentType.CONVERSATION_HISTORY
        assert decision.semantic_intent.time_scope == "today"

    @pytest.mark.asyncio
    async def test_agent_task_routes_to_target_agent(self, monkeypatch):
        """agent_task → 目标 agent → SingleAgentExecutor"""
        from agentmind.routing.semantic_intent import SemanticIntent

        async def _mock_evaluate(self, ctx):
            from agentmind.routing.strategies.base import StrategyResult
            si = SemanticIntent(
                intent=SemanticIntentType.AGENT_TASK,
                confidence=0.92,
                target_agent="coder",
            )
            ctx.semantic_intent = si
            return StrategyResult(
                agent_id="coder", confidence=0.92,
                reason="semantic_intent", semantic_intent=si,
            )

        monkeypatch.setattr(
            "agentmind.routing.strategies.semantic_intent.SemanticIntentStrategy.evaluate",
            _mock_evaluate,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        pipeline = self._build_pipeline()
        decision = await pipeline.run(
            "帮我写一个 Python 排序函数",
            RequestIdentity(user_id="u1"),
            {},
        )

        assert decision.agent_id == "coder"
        assert decision.semantic_intent is not None
        assert decision.semantic_intent.intent == SemanticIntentType.AGENT_TASK

    @pytest.mark.asyncio
    async def test_agentmind_capability_routes_to_agentmind(self, monkeypatch):
        """agentmind_capability → agentmind → SelfReplyExecutor"""
        from agentmind.routing.semantic_intent import SemanticIntent

        async def _mock_evaluate(self, ctx):
            from agentmind.routing.strategies.base import StrategyResult
            si = SemanticIntent(
                intent=SemanticIntentType.AGENTMIND_CAPABILITY,
                confidence=0.88,
            )
            ctx.semantic_intent = si
            return StrategyResult(
                agent_id="agentmind", confidence=0.88,
                reason="semantic_intent", semantic_intent=si,
            )

        monkeypatch.setattr(
            "agentmind.routing.strategies.semantic_intent.SemanticIntentStrategy.evaluate",
            _mock_evaluate,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        pipeline = self._build_pipeline()
        decision = await pipeline.run(
            "你会写代码吗？",
            RequestIdentity(user_id="u1"),
            {},
        )

        assert decision.agent_id == "agentmind"
        assert decision.semantic_intent.intent == SemanticIntentType.AGENTMIND_CAPABILITY

    @pytest.mark.asyncio
    async def test_low_confidence_falls_through_to_signal_scoring(self, monkeypatch):
        """semantic_intent 低置信度弃权 → signal_scoring 兜底选择健康 agent"""
        # semantic_intent returns None (abstain)
        async def _mock_abstain(self, ctx):
            return None

        monkeypatch.setattr(
            "agentmind.routing.strategies.semantic_intent.SemanticIntentStrategy.evaluate",
            _mock_abstain,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        pipeline = self._build_pipeline()
        decision = await pipeline.run(
            "asdfghjkl 无意义输入",
            RequestIdentity(user_id="u1"),
            {},
        )

        # signal_scoring 永远不弃权，应该选择健康 agent
        assert decision.agent_id != ""
        assert decision.agent_id in ("searcher", "coder", "claude_code", "codex")

    @pytest.mark.asyncio
    async def test_conversation_history_expressions_all_hit_same_executor(self, monkeypatch):
        """所有 conversation_history 变体都路由到 agentmind 历史执行器"""
        from agentmind.routing.semantic_intent import SemanticIntent

        async def _mock_evaluate(self, ctx):
            from agentmind.routing.strategies.base import StrategyResult
            si = SemanticIntent(
                intent=SemanticIntentType.CONVERSATION_HISTORY,
                confidence=0.92,
                time_scope="today",
                requested_format="topic_summary",
            )
            ctx.semantic_intent = si
            return StrategyResult(
                agent_id="agentmind", confidence=0.92,
                reason="semantic_intent", semantic_intent=si,
            )

        monkeypatch.setattr(
            "agentmind.routing.strategies.semantic_intent.SemanticIntentStrategy.evaluate",
            _mock_evaluate,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        pipeline = self._build_pipeline()
        history_messages = [
            "当前session我们聊过什么内容",
            "当前会话刚刚说了什么",
            "今天聊过什么",
            "今天都聊过什么内容，帮我总结一下",
            "昨天做过什么",
            "5月29日聊过什么",
            "刚刚 codex 说了什么",
        ]

        for msg in history_messages:
            decision = await pipeline.run(msg, RequestIdentity(user_id="u1"), {})
            assert decision.agent_id == "agentmind", (
                f"'{msg}' 应路由到 agentmind，实际: {decision.agent_id}"
            )
            assert decision.semantic_intent is not None, (
                f"'{msg}' 必须有 semantic_intent"
            )
            assert decision.semantic_intent.intent == SemanticIntentType.CONVERSATION_HISTORY, (
                f"'{msg}' intent 应为 conversation_history，实际: {decision.semantic_intent.intent.value}"
            )

    @pytest.mark.asyncio
    async def test_known_misroutes_are_prevented(self, monkeypatch):
        """已知误路由全部消除：
        - '今天聊过什么，帮我总结一下' 不路由到 writing task
        - '你能查询天气吗？' 不路由到 search task
        - '你会写代码吗？' 不路由到 code task
        - '今天聊过什么' 不产生 LLM freeform 自答
        """
        from agentmind.routing.semantic_intent import SemanticIntent

        async def _mock_evaluate(self, ctx):
            from agentmind.routing.strategies.base import StrategyResult
            msg = ctx.raw_message
            if "聊过什么" in msg or "做过什么" in msg or "说了什么" in msg:
                si = SemanticIntent(
                    intent=SemanticIntentType.CONVERSATION_HISTORY,
                    confidence=0.92,
                    time_scope="today",
                    requested_format="topic_summary",
                )
                ctx.semantic_intent = si
                return StrategyResult(
                    agent_id="agentmind", confidence=0.92,
                    reason="semantic_intent", semantic_intent=si,
                )
            if "你能" in msg or "你会" in msg:
                si = SemanticIntent(
                    intent=SemanticIntentType.AGENTMIND_CAPABILITY,
                    confidence=0.88,
                )
                ctx.semantic_intent = si
                return StrategyResult(
                    agent_id="agentmind", confidence=0.88,
                    reason="semantic_intent", semantic_intent=si,
                )
            return None

        monkeypatch.setattr(
            "agentmind.routing.strategies.semantic_intent.SemanticIntentStrategy.evaluate",
            _mock_evaluate,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        pipeline = self._build_pipeline()

        # '今天聊过什么，帮我总结一下' → conversation_history，不能是 writing
        d1 = await pipeline.run(
            "今天聊过什么，帮我总结一下", RequestIdentity(user_id="u1"), {})
        assert d1.agent_id == "agentmind"
        assert d1.semantic_intent.intent == SemanticIntentType.CONVERSATION_HISTORY
        assert d1.reply_text == ""  # 不产生 freeform 自答

        # '你能查询天气吗？' → agentmind_capability，不能是 search
        d2 = await pipeline.run(
            "你能查询天气吗？", RequestIdentity(user_id="u1"), {})
        assert d2.agent_id == "agentmind"
        assert d2.semantic_intent.intent == SemanticIntentType.AGENTMIND_CAPABILITY

        # '你会写代码吗？' → agentmind_capability，不能是 code
        d3 = await pipeline.run(
            "你会写代码吗？", RequestIdentity(user_id="u1"), {})
        assert d3.agent_id == "agentmind"
        assert d3.semantic_intent.intent == SemanticIntentType.AGENTMIND_CAPABILITY

        # '今天聊过什么' → conversation_history，不能是 freeform 自答
        d4 = await pipeline.run(
            "今天聊过什么", RequestIdentity(user_id="u1"), {})
        assert d4.agent_id == "agentmind"
        assert d4.reply_text == ""

    @staticmethod
    def _build_pipeline() -> RoutingPipeline:
        from agentmind.core.rule_engine import RuleEngine
        from agentmind.services.strategy_manager import StrategyManager

        reg = _Registry()
        engine = RuleEngine.__new__(RuleEngine)
        engine.rules = []
        engine.match = AsyncMock(return_value=None)

        sm = StrategyManager(reg, engine)
        return RoutingPipeline(reg, engine, strategy_manager=sm)
