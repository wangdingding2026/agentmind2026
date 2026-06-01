import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import FastAPI

from agentmind.agents.registry import AgentRegistry
from agentmind.core.rule_engine import RuleEngine
from agentmind.routing.pipeline import RoutingPipeline
from agentmind.services.routing_service import RoutingService


def build_app(tmp_dir: Path):
    agents_path = tmp_dir / "config" / "agents.yaml"
    routes_path = tmp_dir / "config" / "routes.yaml"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_path.write_text(
        yaml.dump({
            "agents": [
                {"id": "mock_echo", "name": "Mock Echo", "type": "cli", "tags": ["general"], "enabled": True, "timeout": 5,
                 "config": {"command": "echo done", "health_check": "echo ok"}},
            ]
        }, allow_unicode=True),
        encoding="utf-8",
    )
    routes_path.write_text(yaml.dump({"rules": []}, allow_unicode=True), encoding="utf-8")
    registry = AgentRegistry(agents_path)
    for ex in registry.executors.values():
        ex.is_healthy = True
    engine = RuleEngine(routes_path, agent_registry=registry)
    app = FastAPI()
    app.state.agent_registry = registry
    app.state.rule_engine = engine
    app.state.settings = {"routing": {"use_new_pipeline": True}}
    return app


def build_app_with_strategy_manager(tmp_dir: Path):
    """与 build_app 相同，但额外设置 strategy_manager 和 routing_pipeline。"""
    app = build_app(tmp_dir)
    from agentmind.services.strategy_manager import StrategyManager
    sm = StrategyManager(app.state.agent_registry, app.state.rule_engine)
    app.state.strategy_manager = sm
    app.state.routing_pipeline = RoutingPipeline(
        app.state.agent_registry, app.state.rule_engine, strategy_manager=sm,
    )
    return app


@pytest.mark.asyncio
async def test_routing_service_route_request_returns_decision(tmp_path):
    app = build_app(tmp_path)
    service = RoutingService(app)

    result = await service.route_request({"message": "写一个函数", "stream": False})

    assert result.agent_id == "mock_echo"
    assert result.trace_id


def test_protocol_router_matches_only_deterministic_protocol_commands(tmp_path):
    from agentmind.routing.protocol_router import ProtocolRouter

    app = build_app(tmp_path)
    router = ProtocolRouter(agent_registry=app.state.agent_registry)

    new_route = router.match("/new")
    explicit_route = router.match("@mock_echo 写代码")
    expand_route = router.match("展开第 2 条")

    assert new_route is not None
    assert new_route.kind == "new_session"
    assert explicit_route is not None
    assert explicit_route.kind == "explicit_agent"
    assert explicit_route.value == "mock_echo"
    assert expand_route is not None
    assert expand_route.kind == "result_set_expand"
    assert expand_route.value == "2"

    assert router.match("今天都聊过什么内容，帮我总结一下") is None
    assert router.match("帮我查今天上海天气") is None
    assert router.match("你可以做什么") is None


@pytest.mark.asyncio
async def test_new_session_protocol_route_bypasses_pipeline(tmp_path, monkeypatch):
    from agentmind.services import routing_service

    app = build_app(tmp_path)
    service = RoutingService(app)

    class FakeMemoryService:
        async def new_session(self, user_id):
            return "conv-new"

    async def fail_if_pipeline_runs(*args, **kwargs):
        raise AssertionError("/new must not enter semantic routing pipeline")

    monkeypatch.setattr(routing_service, "MemoryService", FakeMemoryService)
    monkeypatch.setattr("agentmind.routing.pipeline.RoutingPipeline.run", fail_if_pipeline_runs)

    response = await service.route_request({
        "message": "/new",
        "user_id": "u1",
        "stream": False,
    })

    body = json.loads(response.body)
    assert body["agent_id"] == "agentmind"
    assert body["status"] == "completed"
    assert "conv-new" in body["result"]


@pytest.mark.asyncio
async def test_explicit_agent_is_handled_by_pipeline_strategy(tmp_path, monkeypatch):
    """@agent_name 通过管道的 ExplicitDirective 策略处理。"""
    app = build_app(tmp_path)
    service = RoutingService(app)

    pipeline_called = False
    from agentmind.routing.pipeline import RoutingPipeline as RP

    original_run = RP.run

    async def track_pipeline_run(self, msg, identity, settings, is_retry=False):
        nonlocal pipeline_called
        pipeline_called = True
        return await original_run(self, msg, identity, settings, is_retry)

    monkeypatch.setattr(RP, "run", track_pipeline_run)

    result = await service.route_request({
        "message": "@mock_echo 写代码",
        "user_id": "u1",
        "stream": False,
    })

    assert pipeline_called
    assert result.agent_id == "mock_echo"
    assert result.trace_id


@pytest.mark.asyncio
async def test_conversation_history_uses_dedicated_executor_in_api_path(tmp_path, monkeypatch):
    from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType
    from agentmind.services import routing_service

    app = build_app(tmp_path)
    service = RoutingService(app)
    intent = SemanticIntent(
        intent=SemanticIntentType.CONVERSATION_HISTORY,
        confidence=0.95,
        time_scope="today",
        requested_format="qa_summary",
    )
    decision = RoutingDecision(
        agent_id="agentmind",
        strategy="semantic_intent",
        semantic_intent=intent,
        context=RoutingContext(
            identity=RequestIdentity(user_id="u_history"),
            raw_message="今天聊过什么",
            semantic_intent=intent,
        ),
    )
    calls = []

    async def fake_resolve(**kwargs):
        return routing_service._PipelineResult(trace_id="trace-history", decision=decision)

    class FakeHistoryExecutor:
        def __init__(self, agent_registry):
            calls.append(("history_init", agent_registry))

        async def run_json(self, received_decision, trace_id, user_id):
            calls.append(("history_json", received_decision, trace_id, user_id))
            from fastapi.responses import JSONResponse
            return JSONResponse(content={
                "agent_id": "agentmind",
                "result": "今天的对话记录",
                "trace_id": trace_id,
                "status": "completed",
            })

    class ForbiddenSelfReplyExecutor:
        def __init__(self, agent_registry):
            raise AssertionError("conversation history must not use SelfReplyExecutor")

    monkeypatch.setattr(routing_service, "_resolve_routing_decision", fake_resolve)
    monkeypatch.setattr(routing_service, "ConversationHistoryExecutor", FakeHistoryExecutor)
    monkeypatch.setattr(routing_service, "SelfReplyExecutor", ForbiddenSelfReplyExecutor)
    monkeypatch.setattr(
        "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
        AsyncMock(),
    )

    response = await service.route_request({
        "message": "今天聊过什么",
        "user_id": "u_history",
        "stream": False,
    })

    body = json.loads(response.body)
    assert body["result"] == "今天的对话记录"
    assert calls == [
        ("history_init", app.state.agent_registry),
        ("history_json", decision, "trace-history", "u_history"),
    ]


@pytest.mark.asyncio
async def test_conversation_history_uses_dedicated_executor_in_text_stream(tmp_path, monkeypatch):
    from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
    from agentmind.routing.semantic_intent import SemanticIntent, SemanticIntentType
    from agentmind.services import routing_service

    app = build_app(tmp_path)
    intent = SemanticIntent(
        intent=SemanticIntentType.CONVERSATION_HISTORY,
        confidence=0.95,
        time_scope="today",
        requested_format="qa_summary",
    )
    decision = RoutingDecision(
        agent_id="agentmind",
        strategy="semantic_intent",
        semantic_intent=intent,
        context=RoutingContext(
            identity=RequestIdentity(user_id="u_history"),
            raw_message="今天聊过什么",
            semantic_intent=intent,
        ),
    )
    calls = []

    async def fake_resolve(**kwargs):
        return routing_service._PipelineResult(trace_id="trace-history", decision=decision)

    class FakeHistoryExecutor:
        def __init__(self, agent_registry):
            calls.append(("history_init", agent_registry))

        async def run_text(self, received_decision, trace_id, user_id):
            calls.append(("history_text", received_decision, trace_id, user_id))
            yield "今天的对话记录"

    class ForbiddenSelfReplyExecutor:
        def __init__(self, agent_registry):
            raise AssertionError("conversation history must not use SelfReplyExecutor")

    monkeypatch.setattr(routing_service, "_resolve_routing_decision", fake_resolve)
    monkeypatch.setattr(routing_service, "ConversationHistoryExecutor", FakeHistoryExecutor)
    monkeypatch.setattr(routing_service, "SelfReplyExecutor", ForbiddenSelfReplyExecutor)

    chunks = [
        chunk async for chunk in routing_service.route_stream(
            "今天聊过什么",
            "u_history",
            app.state.agent_registry,
            app.state.rule_engine,
            app.state.settings,
        )
    ]

    assert chunks == ["【AgentMind】\n", "今天的对话记录"]
    assert calls == [
        ("history_init", app.state.agent_registry),
        ("history_text", decision, "trace-history", "u_history"),
    ]


# ═══════════════════════════════════════
# Phase 8: 统一飞书路径和 API 路径
# ═══════════════════════════════════════

class TestPhase8UnifiedRouting:
    """阶段 8：飞书路径和 API 路径使用同一策略配置。"""

    @pytest.mark.asyncio
    async def test_api_fallback_uses_app_state_strategy_manager(self, tmp_path, monkeypatch):
        """_route_request_impl 的 fallback 路径使用 app.state.strategy_manager
        而非创建新的默认 StrategyManager。"""
        app = build_app(tmp_path)
        from agentmind.services.strategy_manager import StrategyManager
        sm = StrategyManager(app.state.agent_registry, app.state.rule_engine)
        sm.set_enabled("semantic_intent", False)
        app.state.strategy_manager = sm
        # 不设置 app.state.routing_pipeline —— 触发 fallback 路径

        pipeline_sm_captured = []

        class _CapturePipeline(RoutingPipeline):
            def __init__(self, agent_registry, rule_engine, strategy_manager=None):
                pipeline_sm_captured.append(strategy_manager)
                super().__init__(agent_registry, rule_engine, strategy_manager=strategy_manager)

        monkeypatch.setattr(
            "agentmind.services.routing_service.RoutingPipeline",
            _CapturePipeline,
        )
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        service = RoutingService(app)
        result = await service.route_request({"message": "写一个函数", "stream": False})

        assert len(pipeline_sm_captured) == 1, "应该创建 1 个 RoutingPipeline"
        captured = pipeline_sm_captured[0]
        assert captured is sm, (
            "fallback 路径必须使用 app.state.strategy_manager，"
            "而不是创建新的默认实例"
        )
        assert result.agent_id == "mock_echo"

    @pytest.mark.asyncio
    async def test_disabled_strategy_in_api_path_takes_effect(self, tmp_path, monkeypatch):
        """禁用策略后 API 路径真实生效 —— 被禁策略不出现在 pipeline 中。"""
        app = build_app(tmp_path)
        from agentmind.services.strategy_manager import StrategyManager
        sm = StrategyManager(app.state.agent_registry, app.state.rule_engine)
        sm.set_enabled("semantic_intent", False)
        app.state.strategy_manager = sm
        app.state.routing_pipeline = RoutingPipeline(
            app.state.agent_registry, app.state.rule_engine, strategy_manager=sm,
        )

        captured_strategy_names = []
        _original_run = RoutingPipeline._run_strategies

        async def _capture_strategies(self, ctx, settings, is_retry):
            enabled = self._strategy_manager.get_enabled_strategies(settings)
            for s in enabled:
                captured_strategy_names.append(type(s).__name__)
            return await _original_run(self, ctx, settings, is_retry)

        monkeypatch.setattr(RoutingPipeline, "_run_strategies", _capture_strategies)
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        service = RoutingService(app)
        result = await service.route_request({"message": "写一个函数", "stream": False})

        assert "SemanticIntentStrategy" not in captured_strategy_names, (
            f"semantic_intent 已禁用，不应出现在策略列表中: {captured_strategy_names}"
        )
        assert result.agent_id == "mock_echo"

    @pytest.mark.asyncio
    async def test_api_and_feishu_path_strategy_order_consistent(self, tmp_path, monkeypatch):
        """API 路径和飞书路径的策略列表一致。"""
        app = build_app(tmp_path)
        from agentmind.services.strategy_manager import StrategyManager
        sm = StrategyManager(app.state.agent_registry, app.state.rule_engine)
        app.state.strategy_manager = sm
        app.state.routing_pipeline = RoutingPipeline(
            app.state.agent_registry, app.state.rule_engine, strategy_manager=sm,
        )

        api_strategies = []
        feishu_strategies = []

        _original_run = RoutingPipeline._run_strategies

        async def _capture_api(self, ctx, settings, is_retry):
            for s in self._strategy_manager.get_enabled_strategies(settings):
                api_strategies.append(type(s).__name__)
            return await _original_run(self, ctx, settings, is_retry)

        monkeypatch.setattr(RoutingPipeline, "_run_strategies", _capture_api)
        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceRecorder.record_decision",
            AsyncMock(),
        )

        # API 路径
        service = RoutingService(app)
        api_result = await service.route_request({"message": "写一个函数", "stream": False})
        assert api_result.agent_id == "mock_echo"

        # 飞书路径：用同一个 sm 创建 pipeline，验证策略顺序相同
        for s in sm.get_enabled_strategies(app.state.settings):
            feishu_strategies.append(type(s).__name__)

        assert api_strategies == feishu_strategies, (
            f"API 策略: {api_strategies}\n飞书策略: {feishu_strategies}"
        )
        assert api_strategies == [
            "ExplicitDirective",
            "SemanticIntentStrategy", "SignalScoringStrategy",
        ]
