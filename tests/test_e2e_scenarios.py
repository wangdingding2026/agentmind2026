"""端到端场景测试：覆盖记忆文件中全部路由功能
─ 对应 agentmind-v3-overview.md 的 14 项功能
─ 对应 agentmind-routing-architecture-upgrade.md 的 4 层架构
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from agentmind.agents.base import AgentCapability, StreamEvent, StreamEventType, TaskResult
from agentmind.routing.context import RequestIdentity, RoutingContext, RoutingDecision
from agentmind.routing.pipeline import RoutingPipeline


# ═══════════════════════════════════════════════════════════
# 场景 1：显式 @agent 指令 — ExplicitDirective 策略
# 对应功能：① 显式前缀 + ④ 语义路由中的 @mention
# ═══════════════════════════════════════════════════════════

class TestScenarioExplicitDirective:
    @pytest.mark.asyncio
    async def test_at_agent_exact_match(self):
        """用户 @agent_id 精确指定 → 直接路由"""
        registry, rule_engine = _make_registry(
            [("claude_code", "Claude Code", ["code"]),
             ("hermes", "Hermes", ["search"])])
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("@claude_code 帮我写代码", identity, {})
        assert decision.agent_id == "claude_code"
        assert decision.confidence == 1.0
        assert "显式" in decision.strategy

    @pytest.mark.asyncio
    async def test_at_agent_name_match(self):
        """用户 @agent名称 模糊匹配 → 路由到正确 Agent"""
        registry, rule_engine = _make_registry(
            [("claude_code", "Claude Code", ["code"])]
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("@Claude 写代码", identity, {})
        assert decision.agent_id == "claude_code"


# ═══════════════════════════════════════════════════════════
# 场景 2：安全拦截 — L0 SensitiveScanner + CandidatePool
# 对应功能：② 安全层实现
# ═══════════════════════════════════════════════════════════

class TestScenarioSecurityIntercept:
    @pytest.mark.asyncio
    async def test_api_key_triggers_flag(self):
        """包含 API Key 的消息 → L0 标记 security_flagged"""
        registry, rule_engine = _make_registry(
            [("local_agent", "Local", ["general"])],
            security_levels={"local_agent": "local"},
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("sk-1234567890abcdefghijklmnopqrstuv", identity, {})
        assert decision.context.security_flagged

    @pytest.mark.asyncio
    async def test_cloud_blocked_on_sensitive(self):
        """敏感消息 + 云端 Agent → L0 过滤只留本地 Agent"""
        registry, rule_engine = _make_registry(
            [
                ("cloud_agent", "Cloud", ["code"], "cloud"),
                ("local_agent", "Local", ["general"], "local"),
            ],
            security_levels={"cloud_agent": "cloud", "local_agent": "local"},
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("sk-1234567890abcdefghijklmnopqrstuv", identity, {})
        # 云端被过滤，只剩本地
        assert decision.agent_id == "local_agent"


# ═══════════════════════════════════════════════════════════
# 场景 3：规则引擎路由 — RuleEngineStrategy
# 对应功能：③ 规则引擎
# ═══════════════════════════════════════════════════════════

class TestScenarioRuleEngine:
    @pytest.mark.asyncio
    async def test_keyword_match_routes_correctly(self):
        """关键词匹配 → 路由到对应 tag 的 Agent"""
        registry, rule_engine = _make_registry_with_rules(
            [("code_agent", "Code Agent", ["code"]),
             ("search_agent", "Search Agent", ["search"])],
            rules=[
                {"name": "code", "type": "keyword", "patterns": ["代码", "写一个"],
                 "target_tags": ["code"], "priority": 10},
                {"name": "search", "type": "keyword", "patterns": ["搜索", "查"],
                 "target_tags": ["search"], "priority": 10},
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("帮我写一个排序函数", identity, {})
        assert decision.agent_id == "code_agent"

    @pytest.mark.asyncio
    async def test_keyword_no_match_signals_fallback(self):
        """无关键词匹配 → SignalScoring 兜底"""
        registry, rule_engine = _make_registry_with_rules(
            [("general_agent", "General", ["general"])],
            rules=[
                {"name": "code", "type": "keyword", "patterns": ["代码"],
                 "target_tags": ["code"], "priority": 10},
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("今天天气怎么样", identity, {})
        assert decision.agent_id == "general_agent"
        assert "信号评分" in decision.strategy or "兜底" in decision.strategy


# ═══════════════════════════════════════════════════════════
# 场景 4：语义路由 — LLMRoutingStrategy（功能 ④）
# ═══════════════════════════════════════════════════════════

class TestScenarioLLMRouting:
    @pytest.mark.asyncio
    async def test_llm_disabled_skips(self):
        """LLM 未配置 → 策略弃权，不阻塞管道"""
        registry, rule_engine = _make_registry(
            [("a1", "Agent 1", ["general"])])
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("hello", identity, {})
        assert decision.agent_id == "a1"  # SignalScoring 兜底


# ═══════════════════════════════════════════════════════════
# 场景 5：信号评分 — SignalScoringStrategy（功能 ⑤）
# ═══════════════════════════════════════════════════════════

class TestScenarioSignalScoring:
    @pytest.mark.asyncio
    async def test_low_cost_preferred(self):
        """低成本 Agent 得分更高"""
        registry, rule_engine = _make_registry(
            [
                ("cheap", "Cheap", ["general"], "local", 0.001, 1.0),
                ("costly", "Costly", ["general"], "local", 0.5, 10.0),
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("普通消息", identity, {})
        assert decision.agent_id == "cheap"

    @pytest.mark.asyncio
    async def test_all_unhealthy_returns_empty(self):
        """所有 Agent 不健康 → 返回空 agent_id"""
        registry, rule_engine = _make_registry(
            [("down", "Down Agent", ["general"])],
            healthy=False,
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("hello", identity, {})
        assert decision.agent_id == ""


# ═══════════════════════════════════════════════════════════
# 场景 6：完整 4 层管道遍历
# 对应：L0 → L1 → L2 → RoutingDecision
# ═══════════════════════════════════════════════════════════

class TestScenarioFullPipeline:
    @pytest.mark.asyncio
    async def test_l0_to_l4_complete_flow(self):
        """正常消息经过全部 4 层"""
        registry, rule_engine = _make_registry_with_rules(
            [("code", "Code Agent", ["code"]),
             ("search", "Search Agent", ["search", "general"])],
            rules=[
                {"name": "code", "type": "keyword", "patterns": ["代码"],
                 "target_tags": ["code"], "priority": 10},
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("写代码", identity, {})
        # L0: 扫描通过，候选池有 code + search
        # L1: SINGLE_TASK
        # L2: 无显式 @ → 规则匹配 "代码" → code_agent
        assert decision.agent_id is not None
        assert decision.context is not None
        assert len(decision.context.candidates) >= 1

    @pytest.mark.asyncio
    async def test_memory_retrieved_in_context(self):
        """L0 MemoryRetriever 检索到的记忆在 context 中"""
        registry, rule_engine = _make_registry(
            [("a1", "Agent 1", ["general"])])
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("继续刚才的任务", identity, {})
        assert decision.context is not None
        assert isinstance(decision.context.memories, list)

    @pytest.mark.asyncio
    async def test_context_preserves_raw_message(self):
        """context.raw_message 保持原始消息不变"""
        registry, rule_engine = _make_registry(
            [("a1", "Agent 1", ["general"])])
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        msg = "帮我分析这段代码的性能瓶颈"
        decision = await pipeline.run(msg, identity, {})
        assert decision.context.raw_message == msg


# ═══════════════════════════════════════════════════════════
# 场景 7：知识保留 — context 不参与路由，只参与执行
# 对应：Phase 4 PromptEnvelope
# ═══════════════════════════════════════════════════════════

class TestScenarioContextInjection:
    def test_envelope_empty_memories(self):
        """无记忆时 PromptEnvelope 保持原消息"""
        from agentmind.routing.envelope import PromptEnvelope
        result = PromptEnvelope.build("hello", [])
        assert result == "hello"

    def test_envelope_injects_memories(self):
        """有记忆时注入上下文前缀"""
        from agentmind.routing.envelope import PromptEnvelope
        mems = [
            {"content": "写一个排序", "summary": "之前写了冒泡排序"},
            {"content": "性能分析", "summary": "分析了时间复杂度"},
        ]
        result = PromptEnvelope.build("优化算法", mems)
        assert "系统注入" in result
        assert "冒泡排序" in result
        assert "时间复杂度" in result
        assert "当前指令：优化算法" in result


# ═══════════════════════════════════════════════════════════
# 场景 8：执行器 fallback_chain 重试
# 对应功能：Phase 4 _execute_with_fallback
# ═══════════════════════════════════════════════════════════

class TestScenarioFallbackChain:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        """主 Agent 成功 → 不触发 fallback"""
        from agentmind.routing.executors.base import ExecutorBase
        registry, _ = _make_registry([("a1", "Agent 1")])
        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = registry

        aid, result, error = await base._execute_with_fallback(["a1"], "msg")
        assert aid == "a1"
        assert result.success
        assert error is None

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_succeeds(self):
        """主 Agent 失败 → 自动切到 fallback_chain 中的下一个"""
        from agentmind.routing.executors.base import ExecutorBase
        registry, _ = _make_registry([("a1", "Agent 1"), ("a2", "Agent 2")])
        # 让 a1 失败
        registry.executors["a1"].execute = AsyncMock(
            return_value=TaskResult(success=False, output="", error="failed"))
        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = registry

        aid, result, error = await base._execute_with_fallback(["a1", "a2"], "msg")
        assert aid == "a2"
        assert result.success

    @pytest.mark.asyncio
    async def test_all_fail_returns_error(self):
        """全部失败 → 返回错误信息"""
        from agentmind.routing.executors.base import ExecutorBase
        registry, _ = _make_registry(
            [("a1", "Agent 1"), ("a2", "Agent 2")],
            healthy=True, succeed=False,
        )
        base = ExecutorBase.__new__(ExecutorBase)
        base._registry = registry

        aid, result, error = await base._execute_with_fallback(["a1", "a2"], "msg")
        assert aid is None
        assert result is None


# ═══════════════════════════════════════════════════════════
# 场景 9：自答路径 — SelfReplyExecutor
# 对应功能：Core LLM self-reply
# ═══════════════════════════════════════════════════════════

class TestScenarioSelfReply:
    @pytest.mark.asyncio
    async def test_self_reply_json(self, monkeypatch):
        """LLM 决定自答 → 返回 agentmind 回复"""
        from agentmind.routing.executors.self_reply import SelfReplyExecutor
        monkeypatch.setattr(
            "agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        decision = RoutingDecision(
            agent_id="agentmind", strategy="LLM 自答", confidence=0.9,
            reply_text="你好，我是 AgentMind，可以帮你调度 Agent 执行任务。",
            context=_make_ctx(),
        )
        registry, _ = _make_registry([])
        executor = SelfReplyExecutor(registry)
        resp = await executor.run_json(decision, "t1", "u1")

        body = json.loads(resp.body.decode())
        assert body["agent_id"] == "agentmind"
        assert "AgentMind" in body["result"]

    @pytest.mark.asyncio
    async def test_self_reply_text(self, monkeypatch):
        """飞书通道自答 → yield 纯文本"""
        from agentmind.routing.executors.self_reply import SelfReplyExecutor
        monkeypatch.setattr(
            "agentmind.routing.executors.self_reply.record_task_update", AsyncMock())
        monkeypatch.setattr(
            "agentmind.routing.executors.base.MemoryWriter.write_task", AsyncMock())

        decision = RoutingDecision(
            agent_id="agentmind", strategy="LLM 自答", confidence=0.9,
            reply_text="text reply",
            context=_make_ctx(),
        )
        registry, _ = _make_registry([])
        executor = SelfReplyExecutor(registry)
        chunks = [c async for c in executor.run_text(decision, "t1", "u1")]
        assert chunks == ["text reply"]


# ═══════════════════════════════════════════════════════════
# 场景 10：追踪记录 — TraceRecorder
# 对应功能：⑭ 可观测性
# ═══════════════════════════════════════════════════════════

class TestScenarioTraceRecording:
    @pytest.mark.asyncio
    async def test_decision_recorded(self, monkeypatch):
        """路由决策被记录到 TraceService"""
        from agentmind.routing.side_effects.trace_recorder import TraceRecorder

        recorded = {}

        class FakeTraceService:
            async def record_decision(self, trace_id, recorded_decision, user_id=""):
                recorded["trace_id"] = trace_id
                recorded["decision"] = recorded_decision
                recorded["user_id"] = user_id

        monkeypatch.setattr(
            "agentmind.routing.side_effects.trace_recorder.TraceService",
            FakeTraceService,
        )

        decision = RoutingDecision(
            agent_id="a1", strategy="规则匹配: code", confidence=0.9,
            fallback_chain=["a2"],
            context=_make_ctx(candidates=["a1", "a2"]),
        )
        await TraceRecorder.record_decision("t1", decision, "u1")
        assert recorded["trace_id"] == "t1"
        assert recorded["user_id"] == "u1"
        assert recorded["decision"].agent_id == "a1"
        assert recorded["decision"].strategy == "规则匹配: code"
        assert recorded["decision"].confidence == 0.9


# ═══════════════════════════════════════════════════════════
# 场景 11：SessionRegistry 流管理
# 对应功能：Peek 流广播
# ═══════════════════════════════════════════════════════════

class TestScenarioSessionRegistry:
    def test_stream_lifecycle(self):
        """注册→广播→回放→注销 完整流程"""
        from agentmind.routing.side_effects.session_registry import SessionRegistry
        sr = SessionRegistry()

        # 广播积压数据
        sr.broadcast_stream_chunk("t1", {"event": "partial", "data": "chunk1"})
        sr.broadcast_stream_chunk("t1", {"event": "partial", "data": "chunk2"})

        # 后续注册的监听器应该收到积压
        q = sr.register_stream_listener("t1")
        backlog = []
        while not q.empty():
            backlog.append(q.get_nowait())
        assert len(backlog) == 2

        # 新广播
        sr.broadcast_stream_chunk("t1", {"event": "partial", "data": "chunk3"})
        assert q.get_nowait()["data"] == "chunk3"

        sr.unregister_stream_listener("t1", q)

    def test_discussion_lifecycle(self):
        """讨论：开始→活跃→停止→结束"""
        from agentmind.routing.side_effects.session_registry import SessionRegistry
        sr = SessionRegistry()

        sr.start_discussion("u1")
        assert sr.is_discussion_active("u1")

        sr.stop_discussion("u1")
        assert not sr.is_discussion_active("u1")

        sr.end_discussion("u1")
        assert "u1" not in sr._discussions


# ═══════════════════════════════════════════════════════════
# 场景 12：Attach 深度接管（管道前置拦截器保留）
# 对应功能：⑩ Attach 深度接管
# ═══════════════════════════════════════════════════════════

class TestScenarioAttach:
    def test_attach_registry_bind_unbind(self):
        """Attach 绑定/解绑 session ↔ trace_id"""
        from agentmind.api.attach_registry import AttachRegistry
        reg = AttachRegistry()
        reg.bind("s1", "t1")
        assert reg.get_bound_task("s1") == "t1"
        reg.unbind("t1")
        assert reg.get_bound_task("s1") is None

    def test_attach_rebind_updates(self):
        """重复绑定同一 session → 更新 trace_id"""
        from agentmind.api.attach_registry import AttachRegistry
        reg = AttachRegistry()
        reg.bind("s1", "t1")
        reg.bind("s1", "t2")
        assert reg.get_bound_task("s1") == "t2"


# ═══════════════════════════════════════════════════════════
# 场景 13：DAG 编排（管道前置拦截器保留）
# 对应功能：⑨ DAG 可视化编排
# ═══════════════════════════════════════════════════════════

class TestScenarioOrchestration:
    def test_validate_dag_no_cycle(self):
        """无环 DAG → 验证通过"""
        from agentmind.api.orchestration import validate_dag
        from agentmind.api.models import OrchestrationStep
        steps = [
            OrchestrationStep(plan_id="p1", step_id=1, agent_id="a1",
                              instruction="step1", depends_on=[]),
            OrchestrationStep(plan_id="p1", step_id=2, agent_id="a2",
                              instruction="step2", depends_on=[1]),
        ]
        validate_dag(steps)  # 不应抛异常

    def test_validate_dag_cycle_detected(self):
        """有环 DAG → 抛出 ValueError"""
        from agentmind.api.orchestration import validate_dag
        from agentmind.api.models import OrchestrationStep
        steps = [
            OrchestrationStep(plan_id="p1", step_id=1, agent_id="a1",
                              instruction="step1", depends_on=[2]),
            OrchestrationStep(plan_id="p1", step_id=2, agent_id="a2",
                              instruction="step2", depends_on=[1]),
        ]
        with pytest.raises(ValueError):
            validate_dag(steps)

    def test_topological_sort_linear(self):
        """线性 DAG → 拓扑排序正确"""
        from agentmind.api.orchestration import topological_sort
        from agentmind.api.models import OrchestrationStep
        steps = [
            OrchestrationStep(plan_id="p1", step_id=2, agent_id="a2",
                              instruction="step2", depends_on=[1]),
            OrchestrationStep(plan_id="p1", step_id=1, agent_id="a1",
                              instruction="step1", depends_on=[]),
        ]
        sorted_steps = topological_sort(steps)
        assert sorted_steps[0].step_id == 1
        assert sorted_steps[1].step_id == 2

    def test_trigger_word_exact_match(self):
        """编排触发词精确子串匹配"""
        from agentmind.api.router import _match_orchestration
        # 无编排文件时返回 None
        result = _match_orchestration("普通消息")
        assert result is None


# ═══════════════════════════════════════════════════════════
# 场景 14：规则引擎边界条件
# 对应功能：③ 规则引擎
# ═══════════════════════════════════════════════════════════

class TestScenarioRuleEngineEdgeCases:
    @pytest.mark.asyncio
    async def test_regex_match(self):
        """正则匹配路由"""
        registry, rule_engine = _make_registry_with_rules(
            [("code", "Code Agent", ["code"])],
            rules=[
                {"name": "regex_test", "type": "regex",
                 "patterns": [r"错误[：:]\s*\d+"],
                 "target_tags": ["code"], "priority": 10},
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("错误：404 找不到页面", identity, {})
        assert decision.agent_id is not None

    @pytest.mark.asyncio
    async def test_priority_order(self):
        """高优先级规则先匹配"""
        registry, rule_engine = _make_registry_with_rules(
            [("high_agent", "High Priority", ["code"]),
             ("low_agent", "Low Priority", ["general"])],
            rules=[
                {"name": "high", "type": "keyword", "patterns": ["紧急"],
                 "target_tags": ["code"], "priority": 20},
                {"name": "low", "type": "keyword", "patterns": ["紧急"],
                 "target_tags": ["general"], "priority": 5},
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("紧急：服务器宕机", identity, {})
        assert decision.agent_id == "high_agent"


# ═══════════════════════════════════════════════════════════
# 场景 15：多 Agent 共存 + 自动选择
# 对应功能：⑥ 流水线整合
# ═══════════════════════════════════════════════════════════

class TestScenarioMultiAgent:
    @pytest.mark.asyncio
    async def test_mixed_security_levels(self):
        """多安全级别 Agent 共存"""
        registry, rule_engine = _make_registry(
            [
                ("local_code", "Local Code", ["code"], "local"),
                ("cloud_general", "Cloud General", ["general"], "cloud"),
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        # 普通消息 → 所有 Agent 可用
        decision = await pipeline.run("hello", identity, {})
        assert decision.agent_id in ("local_code", "cloud_general")

    @pytest.mark.asyncio
    async def test_different_cost_latency(self):
        """不同成本/延迟的 Agent → 信号评分择优"""
        registry, rule_engine = _make_registry(
            [
                ("fast", "Fast Agent", ["general"], "local", 0.001, 0.5),
                ("slow", "Slow Agent", ["general"], "local", 1.0, 30.0),
                ("mid", "Mid Agent", ["general"], "local", 0.1, 5.0),
            ],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("hello", identity, {})
        # 最快最便宜的应被选中
        assert decision.agent_id == "fast"


# ═══════════════════════════════════════════════════════════
# 场景 16：路由决策元数据完整性
# ═══════════════════════════════════════════════════════════

class TestScenarioDecisionMetadata:
    @pytest.mark.asyncio
    async def test_decision_has_all_fields(self):
        """RoutingDecision 包含所有必要字段"""
        registry, rule_engine = _make_registry_with_rules(
            [("a1", "Agent 1", ["code"])],
            rules=[{"name": "code", "type": "keyword", "patterns": ["代码"],
                    "target_tags": ["code"], "priority": 10}],
        )
        pipeline = RoutingPipeline(registry, rule_engine)
        identity = RequestIdentity(trace_id="t1", user_id="u1")

        decision = await pipeline.run("写代码", identity, {})
        assert hasattr(decision, "agent_id")
        assert hasattr(decision, "strategy")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "fallback_chain")
        assert hasattr(decision, "reply_text")
        assert hasattr(decision, "context")
        assert decision.confidence > 0


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_ctx(**kw):
    from agentmind.routing.context import RequestIdentity, RoutingContext
    identity = RequestIdentity(
        trace_id=kw.pop("trace_id", "t1"),
        user_id=kw.pop("user_id", "u1"),
    )
    return RoutingContext(
        identity=identity,
        raw_message=kw.pop("raw_message", "hello"),
        memories=kw.pop("memories", []),
        candidates=kw.pop("candidates", ["a1", "a2"]),
        **kw,
    )


def _make_registry(
    agents: list,
    healthy: bool = True,
    succeed: bool = True,
    security_levels: dict = None,
):
    """创建测试用 AgentRegistry + RuleEngine。
    agents: [(id, name, tags), ...] 或 [(id, name, tags, security_level), ...]
    或 [(id, name, tags, security_level, cost, latency), ...]
    """
    from agentmind.agents.registry import AgentRegistry
    from agentmind.core.rule_engine import RuleEngine

    executors = {}
    for item in agents:
        aid = item[0]
        name = item[1]
        tags = item[2] if len(item) > 2 else ["general"]
        sec = item[3] if len(item) > 3 else "local"
        cost = item[4] if len(item) > 4 else 0.01
        latency = item[5] if len(item) > 5 else 1.0

        cap = AgentCapability(
            id=aid, name=name, type="cli", tags=tags,
            description=f"{name} agent", enabled=True, timeout=5,
            security_level=sec,
            estimated_cost=cost, avg_latency=latency,
        )
        from agentmind.agents.cli_executor import CLIExecutor
        ex = CLIExecutor(cap)
        ex.is_healthy = healthy
        if succeed:
            ex.execute = AsyncMock(
                return_value=TaskResult(success=True, output=f"output from {aid}"))
        else:
            ex.execute = AsyncMock(
                return_value=TaskResult(success=False, output="", error=f"{aid} failed"))
        executors[aid] = ex

    class MockRegistry:
        def __init__(self):
            self.executors = executors

        def get_executor(self, aid):
            return self.executors.get(aid)

    registry = MockRegistry()

    # 空规则引擎
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    tmp.write("rules: []")
    tmp.flush()
    rule_engine = RuleEngine(Path(tmp.name))
    rule_engine.rules = []

    return registry, rule_engine


def _make_registry_with_rules(agents: list, rules: list):
    """创建带规则的 AgentRegistry + RuleEngine"""
    registry, _ = _make_registry(agents)

    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump({"rules": rules}, tmp, allow_unicode=True)
    tmp.flush()
    from agentmind.core.rule_engine import RuleEngine
    rule_engine = RuleEngine(Path(tmp.name), agent_registry=registry)

    return registry, rule_engine
