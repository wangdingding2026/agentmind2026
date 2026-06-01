import pytest

from agentmind.agents.base import AgentCapability
from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision


def test_semantic_intent_from_valid_llm_json():
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType

    payload = {
        "intent": "conversation_history",
        "confidence": 0.92,
        "target_agent": "",
        "time_scope": "today",
        "current_session": False,
        "agent_filter": "",
        "requested_format": "qa_summary",
        "reason": "用户询问今天聊过什么",
    }

    intent = SemanticIntent.from_llm_payload(payload)

    assert intent.intent == SemanticIntentType.CONVERSATION_HISTORY
    assert intent.confidence == 0.92
    assert intent.target_agent == ""
    assert intent.time_scope == "today"
    assert intent.current_session is False
    assert intent.agent_filter == ""
    assert intent.requested_format == "qa_summary"
    assert intent.reason == "用户询问今天聊过什么"


def test_semantic_intent_invalid_payload_becomes_unknown():
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType

    intent = SemanticIntent.from_llm_payload({"intent": "freeform_reply", "confidence": 0.99})

    assert intent.intent == SemanticIntentType.UNKNOWN
    assert intent.confidence == 0.0


def test_semantic_intent_clamps_confidence():
    from agentmind.routing.semantic_intent import SemanticIntent

    high = SemanticIntent.from_llm_payload({"intent": "agent_task", "confidence": 2})
    low = SemanticIntent.from_llm_payload({"intent": "agent_task", "confidence": -1})

    assert high.confidence == 1.0
    assert low.confidence == 0.0


def test_routing_context_and_decision_accept_semantic_intent():
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType

    intent = SemanticIntent(
        intent=SemanticIntentType.AGENTMIND_CAPABILITY,
        confidence=0.8,
        reason="用户询问 AgentMind 能力",
    )

    ctx = RoutingContext(
        identity=RequestIdentity(user_id="u1"),
        raw_message="你会写代码吗？",
        semantic_intent=intent,
    )
    decision = RoutingDecision(
        agent_id="agentmind",
        confidence=0.8,
        semantic_intent=intent,
        context=ctx,
    )

    assert ctx.semantic_intent is intent
    assert decision.semantic_intent is intent


def test_strategy_result_accepts_semantic_intent():
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType
    from agentmind.routing.strategies.base import StrategyResult

    intent = SemanticIntent(
        intent=SemanticIntentType.AGENT_TASK,
        confidence=0.9,
        target_agent="codex",
    )

    result = StrategyResult(
        agent_id="codex",
        confidence=0.9,
        semantic_intent=intent,
    )

    assert result.semantic_intent is intent


class _Executor:
    def __init__(self, agent_id: str, *, healthy: bool = True, tags: list[str] | None = None):
        self.is_healthy = healthy
        self.capability = AgentCapability(
            id=agent_id,
            name=agent_id,
            type="cli",
            tags=tags or [],
            description=f"{agent_id} capability",
            enabled=True,
            timeout=5,
        )


class _Registry:
    def __init__(self, executors: dict[str, _Executor]):
        self.executors = executors

    def get_executor(self, agent_id: str):
        return self.executors.get(agent_id)


class _SemanticIntentStrategyForTest:
    def __init__(self, payload: dict):
        from agentmind.routing.strategies.semantic_intent import SemanticIntentStrategy

        class Strategy(SemanticIntentStrategy):
            async def _call_llm(self, prompt: str, cfg: dict) -> dict | None:
                self.last_prompt = prompt
                return payload

        self.strategy = Strategy(
            _Registry({
                "searcher": _Executor("searcher", tags=["search"]),
                "coder": _Executor("coder", tags=["code"]),
                "down": _Executor("down", healthy=False, tags=["search"]),
            }),
            {"core_llm": {"enabled": True, "endpoint": "http://llm.local"}},
        )


@pytest.mark.asyncio
async def test_semantic_intent_strategy_routes_history_to_agentmind_without_reply_text():
    from agentmind.routing.semantic_intent import SemanticIntentType

    holder = _SemanticIntentStrategyForTest({
        "intent": "conversation_history",
        "confidence": 0.94,
        "time_scope": "today",
        "requested_format": "qa_summary",
        "reason": "询问今天聊过什么",
    })
    ctx = RoutingContext(
        identity=RequestIdentity(user_id="u1"),
        raw_message="今天都聊过什么内容，帮我总结一下",
        candidates=["searcher", "coder"],
    )

    result = await holder.strategy.evaluate(ctx)

    assert result is not None
    assert result.agent_id == "agentmind"
    assert result.reply_text == ""
    assert result.semantic_intent is not None
    assert result.semantic_intent.intent == SemanticIntentType.CONVERSATION_HISTORY
    assert ctx.semantic_intent is result.semantic_intent
    assert "不要直接生成历史答案" in holder.strategy.last_prompt


@pytest.mark.asyncio
async def test_semantic_intent_strategy_routes_agent_task_to_healthy_target_agent():
    from agentmind.routing.semantic_intent import SemanticIntentType

    holder = _SemanticIntentStrategyForTest({
        "intent": "agent_task",
        "confidence": 0.91,
        "target_agent": "searcher",
        "reason": "需要搜索能力",
    })
    ctx = RoutingContext(
        identity=RequestIdentity(user_id="u1"),
        raw_message="帮我查今天上海天气",
        candidates=["searcher", "coder"],
    )

    result = await holder.strategy.evaluate(ctx)

    assert result is not None
    assert result.agent_id == "searcher"
    assert result.reply_text == ""
    assert result.semantic_intent is not None
    assert result.semantic_intent.intent == SemanticIntentType.AGENT_TASK


@pytest.mark.asyncio
async def test_semantic_intent_strategy_abstains_for_unknown_low_confidence_or_unhealthy_target():
    cases = [
        {"intent": "unknown", "confidence": 0.99},
        {"intent": "conversation_history", "confidence": 0.3},
        {"intent": "agent_task", "confidence": 0.92, "target_agent": "down"},
        {"intent": "agent_task", "confidence": 0.92, "target_agent": "missing"},
    ]

    for payload in cases:
        holder = _SemanticIntentStrategyForTest(payload)
        ctx = RoutingContext(
            identity=RequestIdentity(user_id="u1"),
            raw_message="测试",
            candidates=["searcher", "coder", "down"],
        )

        result = await holder.strategy.evaluate(ctx)

        assert result is None


@pytest.mark.asyncio
async def test_semantic_intent_strategy_routes_capability_question_to_agentmind():
    from agentmind.routing.semantic_intent import SemanticIntentType

    holder = _SemanticIntentStrategyForTest({
        "intent": "agentmind_capability",
        "confidence": 0.88,
        "reason": "询问 AgentMind 是否能查天气",
    })
    ctx = RoutingContext(
        identity=RequestIdentity(user_id="u1"),
        raw_message="你能查询天气吗？",
        candidates=["searcher", "coder"],
    )

    result = await holder.strategy.evaluate(ctx)

    assert result is not None
    assert result.agent_id == "agentmind"
    assert result.reply_text == ""
    assert result.semantic_intent is not None
    assert result.semantic_intent.intent == SemanticIntentType.AGENTMIND_CAPABILITY
